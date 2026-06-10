"""Per-segment capacity_tightness extractors (M2 stopgap).

`capacity_tightness` is the one sub-score computed from the
`signals` table. Only 2 of 10 segments have meaningful extractors
in M2:

- `power_generation_oem`: combine `planned_capacity_mw` (forward
  additions from 860M) and `capacity_mw` (operating capacity from
  eia_v2_capacity). The score reflects the ratio of forward
  additions to operating capacity — high ratio = supply is racing
  to catch demand = tighter.

- `data_center_shell`: use `retail_sales_mwh` YoY growth from
  eia_v2 as a proxy for shell demand pull. A 25% YoY is at the
  top of the band; flat is in the middle.

The other 8 segments return None. The formula treats None as
"no value" and the segment gets `data_completeness = 4/5 = 0.8`.
The classifier still produces a regime from the 4 research
sub-scores; NO_DATA is reserved for `data_completeness < 0.4`.

All extractors clamp their output to [0, 1].
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Protocol

from bottlewatch.app.score.ontology_segments import SEGMENT_TO_ROLE_CLASS


class SignalLike(Protocol):
    """Duck-typed view over a Signal row.

    Defined as a Protocol so extractors can be tested with bare
    dataclass instances and so the recompute job can pass either
    ORM rows or `to_row()` dicts without conversion.
    """

    signal_name: str
    value_num: float | None
    observed_at: object  # datetime.date or str; extractors use only the float


def capacity_tightness(segment: str, signals: Iterable[SignalLike]) -> float | None:
    """Dispatch to the per-segment extractor. Returns a value in
    [0, 1] or None if the segment has no extractor in M2.
    """
    match segment:
        case "power_generation_oem":
            return _power_tightness(list(signals))
        case "data_center_shell":
            return _data_center_shell_tightness(list(signals))
        case "transformers_tnd":
            return _transformer_tightness(list(signals))
        case _:
            return None


def _transformer_tightness(signals: list[SignalLike]) -> float | None:
    """Use ppi_transformers growth as a proxy for T&D tightness.

    PPI growth is a strong lead indicator for transformer lead times
    and supply-demand imbalance.
    - 0% YoY growth -> 0.4 (stable/loose)
    - 15% YoY growth -> 0.7 (tight)
    - 30%+ YoY growth -> 1.0 (extremely tight)
    """
    values: list[tuple[object, float]] = []
    for s in signals:
        if s.signal_name == "ppi_transformers" and s.value_num is not None:
            values.append((s.observed_at, s.value_num))
    if len(values) < 13:
        return None
    values.sort(key=lambda x: _to_date(x[0]))
    latest = values[-1][1]
    year_ago = values[-13][1]
    if year_ago <= 0:
        return None
    yoy = (latest - year_ago) / year_ago
    # Map [0.0, 0.30] -> [0.4, 1.0]
    if yoy <= 0:
        return 0.4
    if yoy >= 0.30:
        return 1.0
    return 0.4 + (yoy / 0.30) * 0.6


def _power_tightness(signals: list[SignalLike]) -> float | None:
    """Combine planned_capacity_mw (forward additions) and
    capacity_mw (operating) into a [0, 1] tightness score.

    The methodology calls for "orders-to-capacity or utilization
    vs long-run mean" (§2.2). Our proxy:
        tightness = forward_additions_0_2y / operating_capacity
    A ratio > 1 means forward additions exceed operating capacity,
    i.e. supply is racing to catch demand → tight.
    Clamp at 1.0 (we cap, not extrapolate).

    The recompute job is expected to pass signals filtered to
    the next 24 months for `planned_capacity_mw` and the latest
    value for `capacity_mw`.
    """
    forward: list[float] = []
    operating: list[float] = []
    for s in signals:
        if s.value_num is None:
            continue
        if s.signal_name == "planned_capacity_mw":
            forward.append(s.value_num)
        elif s.signal_name == "capacity_mw":
            operating.append(s.value_num)
    if not forward or not operating:
        return None
    forward_sum = sum(forward)
    operating_level = max(operating)
    if operating_level <= 0:
        return None
    return min(forward_sum / operating_level, 1.0)


def _data_center_shell_tightness(signals: list[SignalLike]) -> float | None:
    """Use retail_sales_mwh YoY growth as a proxy for shell demand.

    The methodology doesn't give a segment-specific IDC formula;
    the proxy is the methodology's "demand_signal" axis applied
    to the data we have (state-level retail sales). A 0% YoY
    reads as 0.5 (median); a 25% YoY reads as 1.0 (max tight).
    Negative growth is clamped to 0.0.

    The recompute job passes the trailing 24 months of
    `retail_sales_mwh` signals sorted ascending by observed_at.
    """
    values: list[tuple[object, float]] = []
    for s in signals:
        if s.signal_name == "retail_sales_mwh" and s.value_num is not None:
            values.append((s.observed_at, s.value_num))
    if len(values) < 13:  # need >=12 months for a YoY delta
        return None
    values.sort(key=lambda x: _to_date(x[0]))
    latest = values[-1][1]
    year_ago = values[-13][1]  # 12 months back
    if year_ago <= 0:
        return None
    yoy = (latest - year_ago) / year_ago
    # Map [-0.10, +0.25] → [0.0, 1.0]; 0.0 YoY → 0.286.
    # The 0.5 midpoint falls at ~+0.075 YoY growth, which is the
    # methodology's median demand-pull case.
    if yoy <= -0.10:
        return 0.0
    if yoy >= 0.25:
        return 1.0
    return (yoy + 0.10) / 0.35


def _to_date(d: object) -> date:
    """Coerce observed_at (date | str) to a date for sorting."""
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d))


# ---------------------------------------------------------------------------
# geo_concentration (ontology-derived, methodology §2.3)
# ---------------------------------------------------------------------------


# Methodology §2.3 floor: regions with <5% share are treated as
# effectively zero. We drop the role instance entirely from the
# count map (a small win for noisy counts where one outlier role
# instance per region would otherwise inflate HHI by 1/n).
_HHI_FLOOR_SHARE = 0.05


def _hhi_from_counts(counts: dict[str, int]) -> float | None:
    """Herfindahl-Hirschman Index from per-region role counts.

    HHI = Σ share_i^2 where share_i = count_i / Σ count_j. Range
    is [1/n, 1] (a single concentrated region -> 1.0; perfectly
    equal across n regions -> 1/n).

    Per methodology §2.3, we apply a 5% floor: any region with
    share < 5% is dropped from the computation. This dampens
    noise from a single role instance registered against an
    unusual region. Returns None if the surviving total is 0.
    """
    if not counts:
        return None
    total = sum(counts.values())
    if total <= 0:
        return None
    qualifying = {region: c for region, c in counts.items() if c / total >= _HHI_FLOOR_SHARE}
    if not qualifying:
        return None
    q_total = sum(qualifying.values())
    if q_total <= 0:
        return None
    return sum((c / q_total) ** 2 for c in qualifying.values())


def _count_regions_for_role(world: Any, role_class: str) -> dict[str, int]:
    """Count role instances per region for the given role class.

    SPARQL aggregation against the ABox. We use the bare prefix
    `<>` (the ontology's default namespace) since the ABox
    individuals all live in `http://bottlewatch.org/ontology#`.
    Returns a dict {region_local_name: count}. An empty dict
    means the role class has no instances or no `operatesIn`
    edges — the caller treats this as "no data" and returns None.
    """
    query = (
        "PREFIX : <http://bottlewatch.org/ontology#> "
        "SELECT ?region (COUNT(?role) AS ?n) WHERE { "
        f"?role a :{role_class} . "
        "?role :operatesIn ?region . "
        "} GROUP BY ?region"
    )
    out: dict[str, int] = {}
    for row in world.sparql(query):
        if not row or len(row) < 2:
            continue
        region, n = row[0], row[1]
        # owlready2 may return either URIRef-ish objects or strings
        # depending on the parser version. Normalize to a local
        # name; if it's already a string, leave it alone.
        if hasattr(region, "name"):
            region_name = region.name
        else:
            region_str = str(region)
            region_name = region_str.rsplit("#", 1)[-1] if "#" in region_str else region_str
        try:
            count = int(n)
        except (TypeError, ValueError):
            continue
        out[region_name] = count
    return out


def geo_concentration(segment: str, world: Any | None = None) -> float | None:
    """Per-segment geographic concentration (HHI of supplier geography).

    Methodology §2.3: HHI by supplier geography in [0, 1]. A segment
    with all its role instances in one region scores 1.0; perfectly
    diversified (post-floor) approaches 1/n. The 5% share floor
    (methodology) drops noisy tail regions.

    The segment→role-class bridge is in `ontology_segments`. A
    segment without a role mapping returns None (the formula
    then falls back to the seed value). `world` is an
    `owlready2.World` whose ontology has been loaded from the
    TBox + ABox. The recompute job loads this once; the
    function is called once per segment.
    """
    if world is None:
        return None
    role_class = SEGMENT_TO_ROLE_CLASS.get(segment)
    if role_class is None:
        return None
    counts = _count_regions_for_role(world, role_class)
    return _hhi_from_counts(counts)
