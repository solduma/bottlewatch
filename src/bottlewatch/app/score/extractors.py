"""Per-segment raw sub-score extractors.

Each public extractor returns an `ExtractorResult` containing the raw
metric value in its natural units and a source key that identifies which
band to use for normalization. The normalization itself (fixed band or
5-year rolling band) lives in `bottlewatch.app.score.normalize`.

`geo_concentration` is the exception: HHI is already a [0, 1]
concentration index, so it returns `float | None` directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Protocol

from bottlewatch.app.score.capex_ledger import Ledger, load_ledger, series_for_segment
from bottlewatch.app.score.ontology_segments import SEGMENT_TO_ROLE_CLASS


# Segments whose demand_signal is driven by the manual hyperscaler AI capex ledger.
_HYPERSCALER_DEMAND_SEGMENTS: frozenset[str] = frozenset(
    {
        "data_center_shell",
        "gpu_asic_silicon",
        "advanced_node_fabs",
        "hbm_memory",
        "networking_interconnect",
        "advanced_packaging",
    }
)


# Segments that can use FRED cross-segment proxies in Phase 1.
# These are stopgaps until segment-specific primary sources land.
_SEMI_SEGMENTS: frozenset[str] = frozenset(
    {
        "advanced_node_fabs",
        "hbm_memory",
        "gpu_asic_silicon",
        "networking_interconnect",
        "advanced_packaging",
    }
)

_MANUFACTURING_SEGMENTS: frozenset[str] = frozenset(
    {
        "systems_rack_scale",
        "cooling_water",
        "power_generation_oem",
    }
)


@dataclass(frozen=True)
class ExtractorResult:
    """Raw extractor output and the band key used for normalization."""

    raw_value: float | None
    source_key: str


class SignalLike(Protocol):
    """Duck-typed view over a Signal row.

    Defined as a Protocol so extractors can be tested with bare
    dataclass instances and so the recompute job can pass either
    ORM rows or `to_row()` dicts without conversion.
    """

    signal_name: str
    value_num: float | None
    observed_at: object  # datetime.date or str; extractors use only the float


# Segments that can use Comtrade trade-volume YoY as a capacity proxy.
_COMTRADE_CAPACITY_SEGMENTS: frozenset[str] = frozenset(
    {
        "hbm_memory",
        "advanced_packaging",
        "transformers_tnd",
    }
)


def capacity_tightness(segment: str, signals: Iterable[SignalLike]) -> ExtractorResult | None:
    """Dispatch to the per-segment capacity_tightness extractor.

    Returns the raw capacity metric and a source key, or None if the
    segment has no extractor. The normalizer will convert the raw value
    to [0, 1].

    Order of priority:
    1. Segment-specific primary extractor (EIA, Comtrade, manufacturing).
    2. SEC EDGAR keyword-count fallback (cross-segment).
    3. None → normalizer imputes 0.5.
    """
    seg_signals = list(signals)
    raw: float | None = None
    source_key = "edgar_keyword"
    match segment:
        case "power_generation_oem":
            raw = _power_tightness(seg_signals)
            source_key = "power_ratio"
        case "data_center_shell":
            raw = _data_center_shell_tightness(seg_signals)
            source_key = "retail_sales_yoy"
        case _:
            if segment in _COMTRADE_CAPACITY_SEGMENTS:
                raw = _comtrade_capacity_tightness(seg_signals)
                source_key = "comtrade_volume"
            elif segment in _MANUFACTURING_SEGMENTS:
                raw = _manufacturing_capacity_tightness(seg_signals)
                source_key = "manufacturing_utilization"
    if raw is not None:
        return ExtractorResult(raw, source_key)
    edgar = _edgar_capacity_tightness(seg_signals)
    if edgar is not None:
        return ExtractorResult(edgar, "edgar_keyword")
    return None


def demand_signal(segment: str, signals: Iterable[SignalLike]) -> ExtractorResult | None:
    """Dispatch to the per-segment demand_signal extractor.

    Returns the raw demand metric and a source key, or None if the
    segment has no dynamic demand extractor in the current data set.
    """
    seg_signals = list(signals)
    match segment:
        case "transformers_tnd":
            raw = _transformer_demand_signal(seg_signals)
            if raw is not None:
                return ExtractorResult(raw, "transformer_orders")
            return None
        case _:
            if segment in _HYPERSCALER_DEMAND_SEGMENTS:
                raw = _hyperscaler_demand_signal(segment)
                if raw is not None:
                    return ExtractorResult(raw, "hyperscaler_capex")
                return None
            if segment in _MANUFACTURING_SEGMENTS:
                raw = _manufacturing_demand_signal(seg_signals)
                if raw is not None:
                    return ExtractorResult(raw, "manufacturing_indpro")
                return None
            return None


def lead_time_growth(segment: str, signals: Iterable[SignalLike]) -> ExtractorResult | None:
    """Dispatch to the per-segment lead_time_growth extractor.

    Returns the raw lead-time metric and a source key, or None if the
    segment has no dynamic lead_time_growth in the current data set.

    Priority:
    - `transformers_tnd`: FRED WPU1321 absolute PPI level.
    - Semi segments: SEMI book-to-bill ratio (primary), with FRED
      `ppi_semis` YoY as a fallback.
    - SEC EDGAR keyword mentions as a cross-segment fallback.
    """
    seg_signals = list(signals)
    match segment:
        case "transformers_tnd":
            raw = _transformer_lead_time_growth(seg_signals)
            if raw is not None:
                return ExtractorResult(raw, "transformers_ppi")
            return None
        case _:
            if segment in _SEMI_SEGMENTS:
                b2b = _semi_book_to_bill_lead_time_growth(seg_signals)
                if b2b is not None:
                    return ExtractorResult(b2b, "semi_book_to_bill")
                ppi = _semi_lead_time_growth(seg_signals)
                if ppi is not None:
                    return ExtractorResult(ppi, "semi_ppi")
    edgar = _edgar_lead_time_growth(seg_signals)
    if edgar is not None:
        return ExtractorResult(edgar, "edgar_keyword")
    return None


def _transformer_demand_signal(signals: list[SignalLike]) -> float | None:
    """Raw YoY growth of FRED `A35SNO` (electrical equipment new orders).

    -10% YoY -> normalized 0.0; +25% YoY -> normalized 1.0 via the fixed
    band in `score_bands.json`.
    """
    values: list[tuple[object, float]] = []
    for s in signals:
        if s.signal_name == "electrical_equipment_orders" and s.value_num is not None:
            values.append((s.observed_at, s.value_num))
    if len(values) < 13:
        return None
    values.sort(key=lambda x: _to_date(x[0]))
    latest = values[-1][1]
    year_ago = values[-13][1]
    if year_ago <= 0:
        return None
    return (latest - year_ago) / year_ago


def _manufacturing_demand_signal(signals: list[SignalLike]) -> float | None:
    """Raw YoY growth of FRED `INDPRO` (industrial production).

    -5% YoY -> normalized 0.0; +10% YoY -> normalized 1.0.
    """
    values: list[tuple[object, float]] = []
    for s in signals:
        if s.signal_name == "industrial_production" and s.value_num is not None:
            values.append((s.observed_at, s.value_num))
    if len(values) < 13:
        return None
    values.sort(key=lambda x: _to_date(x[0]))
    latest = values[-1][1]
    year_ago = values[-13][1]
    if year_ago <= 0:
        return None
    return (latest - year_ago) / year_ago


def _hyperscaler_demand_signal(
    segment: str,
    ledger: Ledger | None = None,
) -> float | None:
    """Raw trailing-4-quarter aggregate AI capex YoY growth.

    Uses the manual hyperscaler AI capex ledger. Returns the YoY ratio
    (e.g. +0.30 = +30%) which the band maps [-0.10, +0.40] -> [0, 1].
    """
    try:
        ledger = ledger if ledger is not None else load_ledger()
    except FileNotFoundError:
        return None
    series = series_for_segment(segment, ledger)
    if series is None or len(series.values) < 5:
        return None
    current = sum(series.values[-4:])
    prior = sum(series.values[-5:-1])
    if prior <= 0:
        return None
    return (current - prior) / prior


def _edgar_keyword_score(
    signals: list[SignalLike],
    keyword_signal_names: set[str],
) -> float | None:
    """Raw trailing-12-month z-score of SEC EDGAR keyword counts.

    The fixed band maps z ∈ [-2, +2] to [0, 1]. Returns None if fewer
    than 6 months of data or zero variance.
    """
    by_month: dict[str, float] = {}
    for s in signals:
        if s.signal_name in keyword_signal_names and s.value_num is not None:
            d = _to_date(s.observed_at)
            key = f"{d.year:04d}-{d.month:02d}"
            by_month[key] = by_month.get(key, 0.0) + s.value_num

    if len(by_month) < 6:
        return None

    months = sorted(by_month.keys())
    totals = [by_month[m] for m in months]
    window = totals[-12:]
    if len(window) < 6:
        return None
    mean = sum(window[:-1]) / len(window[:-1])
    std = _std(window[:-1])
    if std == 0:
        latest = window[-1]
        if latest == mean:
            return 0.0  # maps to 0.5 after normalization
        return 1.0 if latest > mean else -1.0
    return (window[-1] - mean) / std


def _std(values: list[float]) -> float:
    """Population standard deviation."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return variance**0.5


def _edgar_lead_time_growth(signals: list[SignalLike]) -> float | None:
    """Raw SEC EDGAR `lead_time_mentions` z-score."""
    return _edgar_keyword_score(signals, {"lead_time_mentions"})


def _edgar_capacity_tightness(signals: list[SignalLike]) -> float | None:
    """Raw SEC EDGAR `shortage_mentions` + `capacity_expansion_mentions` z-score."""
    return _edgar_keyword_score(signals, {"shortage_mentions", "capacity_expansion_mentions"})


def _manufacturing_capacity_tightness(signals: list[SignalLike]) -> float | None:
    """Raw FRED `TCU` (capacity utilization) level.

    The fixed band maps [75, 90] -> [0, 1].
    """
    values: list[tuple[object, float]] = []
    for s in signals:
        if s.signal_name == "capacity_utilization" and s.value_num is not None:
            values.append((s.observed_at, s.value_num))
    if not values:
        return None
    values.sort(key=lambda x: _to_date(x[0]))
    return values[-1][1]


def _transformer_lead_time_growth(signals: list[SignalLike]) -> float | None:
    """Raw FRED `WPU1321` (transformer PPI) absolute level.

    The fixed band maps [80, 350] -> [0, 1].
    """
    values: list[tuple[object, float]] = []
    for s in signals:
        if s.signal_name == "ppi_transformers" and s.value_num is not None:
            values.append((s.observed_at, s.value_num))
    if len(values) < 2:
        return None
    values.sort(key=lambda x: _to_date(x[0]))
    return values[-1][1]


def _semi_book_to_bill_lead_time_growth(signals: list[SignalLike]) -> float | None:
    """Raw SEMI book-to-bill ratio.

    The fixed band maps [0.8, 1.4] -> [0, 1].
    """
    values: list[tuple[object, float]] = []
    for s in signals:
        if s.signal_name == "book_to_bill_ratio" and s.value_num is not None:
            values.append((s.observed_at, s.value_num))
    if not values:
        return None
    values.sort(key=lambda x: _to_date(x[0]))
    return values[-1][1]


def _semi_lead_time_growth(signals: list[SignalLike]) -> float | None:
    """Raw FRED `WPU31132506` (semiconductor PPI) YoY growth.

    The fixed band maps [-10%, +25%] -> [0, 1].
    """
    values: list[tuple[object, float]] = []
    for s in signals:
        if s.signal_name == "ppi_semis" and s.value_num is not None:
            values.append((s.observed_at, s.value_num))
    if len(values) < 13:
        return None
    values.sort(key=lambda x: _to_date(x[0]))
    latest = values[-1][1]
    year_ago = values[-13][1]
    if year_ago <= 0:
        return None
    return (latest - year_ago) / year_ago


def _power_tightness(signals: list[SignalLike]) -> float | None:
    """Raw ratio of forward additions to operating capacity.

    Returns the unclamped ratio so rolling normalization can use the
    actual historical range. The fixed band maps [0, 1] -> [0, 1].
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
    return forward_sum / operating_level


def _data_center_shell_tightness(signals: list[SignalLike]) -> float | None:
    """Raw retail_sales_mwh YoY growth for data-center shell proxy.

    The fixed band maps [-10%, +25%] -> [0, 1].
    """
    values: list[tuple[object, float]] = []
    for s in signals:
        if s.signal_name == "retail_sales_mwh" and s.value_num is not None:
            values.append((s.observed_at, s.value_num))
    if len(values) < 13:
        return None
    values.sort(key=lambda x: _to_date(x[0]))
    latest = values[-1][1]
    year_ago = values[-13][1]
    if year_ago <= 0:
        return None
    return (latest - year_ago) / year_ago


def _comtrade_capacity_tightness(signals: list[SignalLike]) -> float | None:
    """Raw UN Comtrade `trade_volume` YoY growth.

    The fixed band maps [-20%, +40%] -> [0, 1].
    """
    values: list[tuple[object, float]] = []
    for s in signals:
        if s.signal_name == "trade_volume" and s.value_num is not None:
            values.append((s.observed_at, s.value_num))
    if len(values) < 13:
        return None
    values.sort(key=lambda x: _to_date(x[0]))
    latest = values[-1][1]
    year_ago = values[-13][1]
    if year_ago <= 0:
        return None
    return (latest - year_ago) / year_ago


def _to_date(d: object) -> date:
    """Coerce observed_at (date | str) to a date for sorting."""
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d))


# ---------------------------------------------------------------------------
# geo_concentration (ontology-derived fallback; methodology §2.3)
# ---------------------------------------------------------------------------


# Methodology §2.3 floor: regions with <5% share are treated as
# effectively zero.
_HHI_FLOOR_SHARE = 0.05


def _hhi_from_counts(counts: dict[str, int]) -> float | None:
    """Herfindahl-Hirschman Index from per-region role counts.

    HHI = Σ share_i^2 where share_i = count_i / Σ count_j. Applies the
    5% share floor from methodology §2.3. Returns None if the surviving
    total is 0.
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

    SPARQL aggregation against the ABox. Returns a dict
    {region_local_name: count}. An empty dict means the role class has
    no instances or no `operatesIn` edges.
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

    This is the ontology fallback path. The preferred path in Phase 2
    is `bottlewatch.app.score.geo.geo_concentration()`, which uses the
    universe CSV directly. This function is kept for comparison and for
    the `GEO_CONCENTRATION_SOURCE=ontology` feature flag.
    """
    if world is None:
        return None
    role_class = SEGMENT_TO_ROLE_CLASS.get(segment)
    if role_class is None:
        return None
    counts = _count_regions_for_role(world, role_class)
    return _hhi_from_counts(counts)
