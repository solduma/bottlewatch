"""Recompute the materialized `scores` table (M2/M3).

Console entry point: `bottlewatch-recompute` (declared in
pyproject.toml's [project.scripts]). Mirrors `refresh_daily.py`'s
`run()/main()` structure for CLI consistency.

What it does:
1. Read the `signals` table for the latest 5y of values per
   (segment, signal_name) to feed both current extractors and the
   rolling 5-year normalization band.
2. Prune score_history and sub_score_history rows older than the
   retention window.
3. Load the trailing 6 months of score_history per (segment, horizon)
   to compute real momentum (B').
4. Load the trailing 5 years of sub_score_history per
   (segment, sub_score_name) to feed the rolling normalizer.
5. For each segment in `scoring_seed.json` and each of 3 horizons,
   call `score.compute_segment_score(...)`, passing raw sub-score
   values and the configured normalization mode.
6. Atomically rebuild the `scores` table and append both score_history
   and sub_score_history rows.
7. Append a JSONL line to `data/cache/refresh.log`.

The job always recomputes (no watermark). Pure compute over the
signals table is sub-second; freshness beats idempotency. The
`/api/v1/health` endpoint reads `MAX(scores.computed_at)` to
surface "is the data stale?" in the dashboard footer.

CLI flags:
- --dry-run : use a /tmp/... DB, do not touch production.
              In dry-run the table is still rebuilt, just in the
              tmp DB — same behavior as `refresh_daily.py`.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import (
    Score,
    ScoreHistory,
    Signal,
    SubScoreHistory,
    make_engine,
    make_session_factory,
    session_scope,
)
from bottlewatch.app.score import compute_segment_score
from bottlewatch.app.score import extractors
from bottlewatch.app.score import geo as geo_module
from bottlewatch.app.score.formula import ScoreResult
from bottlewatch.app.score.normalize import BANDS_FROZEN_SINCE, BANDS_VERSION
from bottlewatch.app.score.regime import THRESHOLDS_FROZEN_SINCE, THRESHOLDS_VERSION
from bottlewatch.app.score.research_values import known_segments
from bottlewatch.config import Settings, get_settings

_LOGGER = logging.getLogger(__name__)

# The recompute job reads the last `_LOOKBACK_DAYS` of signals per
# segment. 1825d (5 years) covers both the longest extractor input
# and the rolling 5-year normalization band.
_LOOKBACK_DAYS = 1825

# EIA-860M stores `observed_at` as the *planned operation date*,
# which is often in the future. The scoring extractor needs to see
# forward additions, so we load `planned_capacity_mw` signals up to
# 36 months ahead of the recompute date. Other signals stay bounded
# by the normal lookback window.
_PLANNED_CAPACITY_LOOKAHEAD_DAYS = 1095


def _dry_run_url(prod_url: str) -> str:
    """Return a URL that isolates dry-run writes from production.

    - For sqlite: writes to /tmp/bottlewatch-dry.db (a fresh file
      the operator can inspect or discard).
    - For postgres: rewrites the URL to scope the session to a
      `bottlewatch_dry` schema. The schema is created in a
      pre-flight step by the caller; recompute itself does not
      create schemas because that would require elevated
      privileges (CREATE SCHEMA) the application user shouldn't
      have in production.

    The caller is responsible for dropping the schema after the
    dry-run finishes. The recompute job's transactional
    `delete + insert` cycle is confined to whatever the session
    can see via the search_path, so the dry-run is safe to run
    against the production database without touching real data.
    """
    if prod_url.startswith("sqlite"):
        return f"sqlite:///{Path('/tmp/bottlewatch-dry.db')}"
    if prod_url.startswith("postgresql"):
        # Append `?options=-c%20search_path%3Dbottlewatch_dry` to
        # the URL. The caller pre-creates this schema.
        sep = "&" if "?" in prod_url else "?"
        return f"{prod_url}{sep}options=-c%20search_path%3Dbottlewatch_dry"
    # Unknown scheme: fall through to the prod URL (the dry-run
    # will write to the real DB; the operator can re-run with
    # --database-url to override).
    return prod_url


@dataclass(frozen=True)
class _SignalRow:
    """Plain-data row passed to `extractors.capacity_tightness`.

    Satisfies the `SignalLike` protocol (attribute access on
    `signal_name`, `value_num`, `observed_at`) without carrying
    a SQLAlchemy session. Constructed in bulk from the SELECT
    below.
    """

    signal_name: str
    value_num: float | None
    observed_at: date


# ---------------------------------------------------------------------------
# Result model (mirrors refresh_daily.RunReport)
# ---------------------------------------------------------------------------


@dataclass
class RunReport:
    """Summary of one recompute run. Returned by `run()` and printed at the end."""

    started_at: datetime
    finished_at: datetime
    dry_run: bool
    rows_written: int
    segments_scored: int
    no_data_count: int
    detail: str = ""

    @property
    def exit_code(self) -> int:
        return 0  # recompute either fully succeeds or raises; errors are fatal

    def to_lines(self) -> list[str]:
        head = "OK" if self.rows_written else "EMPTY"
        return [
            f"bottlewatch-recompute: {head} ({self.rows_written} rows, "
            f"{self.segments_scored} segments scored, "
            f"{self.no_data_count} NO_DATA) {self.detail}".rstrip(),
        ]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def _load_signals_by_segment(
    factory: sessionmaker,
    since: datetime,
    until: datetime,
    as_of: datetime | None = None,
) -> dict[str, list[_SignalRow]]:
    """Read signals for the scoring window, grouped by segment.

    Most signals are loaded from `since` through `until`.  EIA-860M
    `planned_capacity_mw` rows are additionally loaded up to
    `_PLANNED_CAPACITY_LOOKAHEAD_DAYS` after `until`, because their
    `observed_at` is the planned operation date in the future.

    When `as_of` is provided, only rows with `ingested_at <= as_of`
    and `observed_at <= as_of.date()` are returned. This is the
    point-in-time path used by the backtest job.

    Dedup contract: for sources where re-emission is the same
    data point (e.g. EIA 860M: the planned addition for plant
    `p1` is the same data whether ingested in January or April),
    only the most recently ingested row per
    `(segment, signal_name, source_id)` is kept. Otherwise
    (e.g. FRED: each monthly `ppi_transformers` value is a
    distinct time-series point), every row is preserved.

    The set of "idempotent" sources is small and explicitly
    enumerated in `_IDEMPOTENT_SOURCES` — the signals table has
    no unique constraint by design, so this is the only place
    the dedup decision lives. Note that 860M's `observed_at` is
    the *planned operation date*, not the ingestion date, so the
    "most recent" tie-breaker is `ingested_at`, not `observed_at`.
    """
    out: dict[str, list[_SignalRow]] = {}
    seen: set[tuple[str, str, str | None]] = set()
    as_of_date = as_of.date() if as_of is not None else None

    def _base_query(session):
        stmt = select(
            Signal.segment,
            Signal.signal_name,
            Signal.source,
            Signal.source_id,
            Signal.value_num,
            Signal.observed_at,
            Signal.ingested_at,
        )
        if as_of is not None:
            stmt = stmt.where(Signal.ingested_at <= as_of).where(Signal.observed_at <= as_of_date)
        return stmt

    # 1. Normal window: all signals within [since, until].
    with session_scope(factory) as session:
        rows = session.execute(
            _base_query(session)
            .where(Signal.observed_at >= since.date())
            .where(Signal.observed_at <= until.date())
            # For idempotent sources, multiple ingestion runs emit
            # rows with the same `observed_at` (it's the planned
            # operation date, invariant across runs) and a fresh
            # `ingested_at` on each. Sort `ingested_at` DESC so the
            # dedup below keeps the most recently ingested copy.
            .order_by(Signal.observed_at.desc(), Signal.ingested_at.desc())
        ).all()
    _add_signal_rows(rows, out, seen)

    # 2. Future planned capacity: EIA-860M `planned_capacity_mw` rows
    # whose planned operation date is after `until` but within the
    # lookahead horizon.  These rows use the same dedup semantics as
    # the normal window.
    future_until = until + timedelta(days=_PLANNED_CAPACITY_LOOKAHEAD_DAYS)
    with session_scope(factory) as session:
        rows = session.execute(
            _base_query(session)
            .where(Signal.signal_name == "planned_capacity_mw")
            .where(Signal.observed_at > until.date())
            .where(Signal.observed_at <= future_until.date())
            .order_by(Signal.observed_at.desc(), Signal.ingested_at.desc())
        ).all()
    _add_signal_rows(rows, out, seen)

    # Re-sort each segment's signals by observed_at ascending so the
    # extractors that depend on a chronological view (YoY, latest
    # vs prior) see the right ordering.
    for seg_signals in out.values():
        seg_signals.sort(key=lambda r: r.observed_at)
    return out


def _add_signal_rows(
    rows: Sequence[Any],
    out: dict[str, list[_SignalRow]],
    seen: set[tuple[str, str, str | None]],
) -> None:
    """Add raw signal rows to `out`, applying idempotent-source dedup."""
    for segment, signal_name, source, source_id, value_num, observed_at, _ingested_at in rows:
        if source in _IDEMPOTENT_SOURCES:
            dedup_key = (segment, signal_name, source_id)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
        out.setdefault(segment, []).append(
            _SignalRow(
                signal_name=signal_name,
                value_num=value_num,
                observed_at=observed_at,
            )
        )


# Sources whose signals are the *same data point* re-emitted on
# each ingestion. EIA 860M's monthly XLSX release re-asserts the
# planned additions for every plant in the operating inventory;
# the value for plant `p1` in April is not a new data point, it's
# the same planned addition observed in January.
#
# FRED is NOT in this set: each `ppi_transformers` value at a
# given `observed_at` is a distinct time-series observation.
_IDEMPOTENT_SOURCES: frozenset[str] = frozenset({"eia_860m"})


def _load_existing_first_computed_at(
    factory: sessionmaker,
) -> dict[tuple[str, str], datetime]:
    """Read the existing `first_computed_at` for each (segment, horizon).

    On the first run the table is empty → returns {}. On subsequent
    runs the recompute preserves the original `first_computed_at`
    so the regime_confidence gating (low/medium/high) accumulates
    correctly over time.
    """
    out: dict[tuple[str, str], datetime] = {}
    with session_scope(factory) as session:
        rows = session.execute(select(Score.segment, Score.horizon, Score.first_computed_at)).all()
    for seg, hor, fca in rows:
        out[(seg, hor)] = fca
    return out


_RETENTION_DAYS = 1000


# ---------------------------------------------------------------------------
# Ontology loading (geo_concentration sub-score; methodology §2.3)
# ---------------------------------------------------------------------------

# Project root: four levels up from this file (src/bottlewatch/jobs/...).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_TBOX = _PROJECT_ROOT / "research" / "05_ontology" / "bottlewatch.owl"
_DEFAULT_ABOX = _PROJECT_ROOT / "research" / "05_ontology" / "instances.ttl"


def load_ontology_world(
    tbox_path: Path | None = None,
    abox_path: Path | None = None,
) -> Any | None:
    """Load the TBox + ABox into a fresh owlready2 world.

    Returns None (and logs a warning) when:
    - the ABox file is missing (operator hasn't run `make ontology` yet)
    - owlready2 is not importable

    We deliberately do NOT run HermiT here: the ABox is built with
    the reasoner already applied, so loading is a simple file read.
    Re-reasoning on every recompute would add ~2-5s for no benefit.
    The validate_ontology.py job still runs HermiT at build time
    to catch any drift.
    """
    tbox = tbox_path or _DEFAULT_TBOX
    abox = abox_path or _DEFAULT_ABOX
    if not abox.exists():
        _LOGGER.warning("ontology ABox missing at %s; geo_concentration will fall back to seed", abox)
        return None
    try:
        import owlready2 as _owlready2
    except ImportError:
        _LOGGER.warning("owlready2 not installed; geo_concentration will fall back to seed")
        return None
    world = _owlready2.World()
    if tbox.exists():
        world.get_ontology(str(tbox.absolute().as_uri())).load()
    world.get_ontology(str(abox.absolute().as_uri())).load()
    return world


def _compute_geo_by_segment(settings: Settings, world: Any | None) -> dict[str, float | None]:
    """Pre-compute HHI for every known segment.

    Uses the universe-weighted HHI when
    `settings.geo_concentration_source == "universe_weighted"`,
    otherwise falls back to the ontology ABox path.
    """
    out: dict[str, float | None] = {}
    if settings.geo_concentration_source == "universe_weighted":
        for segment in known_segments():
            out[segment] = geo_module.geo_concentration(segment)
        return out
    if world is None:
        return {}
    for segment in known_segments():
        out[segment] = extractors.geo_concentration(segment, world)
    return out


def _compute_demand_signal_by_segment(
    signals_by_segment: dict[str, list[Any]],
) -> dict[str, extractors.ExtractorResult | None]:
    """Pre-compute the dynamic `demand_signal` sub-score for every
    known segment. Returns raw ExtractorResults (or None when the
    segment has no dynamic extractor). The formula falls back to the
    static seed value when None.
    """
    out: dict[str, extractors.ExtractorResult | None] = {}
    for segment in known_segments():
        seg_signals = signals_by_segment.get(segment, [])
        out[segment] = extractors.demand_signal(segment, seg_signals)
    return out


def _compute_lead_time_by_segment(
    signals_by_segment: dict[str, list[Any]],
) -> dict[str, extractors.ExtractorResult | None]:
    """Pre-compute the dynamic `lead_time_growth` sub-score for
    every known segment. Returns a dict segment -> score (or None
    when the segment has no dynamic extractor in the current data
    set).

    Mirrors `_compute_geo_by_segment` and
    `_compute_demand_signal_by_segment`. Currently only
    `transformers_tnd` has a dynamic lead_time_growth (FRED
    `WPU1321` transformer PPI absolute level). The other segments
    fall back to the static seed value in `research_values`.
    """
    out: dict[str, extractors.ExtractorResult | None] = {}
    for segment in known_segments():
        seg_signals = signals_by_segment.get(segment, [])
        out[segment] = extractors.lead_time_growth(segment, seg_signals)
    return out


def _load_score_history(
    factory: sessionmaker,
    until: datetime,
    as_of: datetime | None = None,
) -> dict[tuple[str, str], list[tuple[datetime, float]]]:
    """Read the trailing 7 months of score_history per (segment, horizon) relative to until.

    When `as_of` is provided, rows are further restricted to
    `computed_at <= as_of` for point-in-time backtests.
    """
    cutoff = until - timedelta(days=210)  # 7 months
    upper = min(until, as_of) if as_of is not None else until
    out: dict[tuple[str, str], list[tuple[datetime, float]]] = {}
    with session_scope(factory) as session:
        rows = session.execute(
            select(ScoreHistory.segment, ScoreHistory.horizon, ScoreHistory.computed_at, ScoreHistory.b)
            .where(ScoreHistory.computed_at >= cutoff)
            .where(ScoreHistory.computed_at < upper)
            .order_by(ScoreHistory.computed_at.asc())
        ).all()
    for seg, hor, comp_at, b in rows:
        if b is not None:
            out.setdefault((seg, hor), []).append((comp_at, b))
    return out


def _load_sub_score_history(
    factory: sessionmaker,
    until: datetime,
    as_of: datetime | None = None,
) -> dict[tuple[str, str], list[tuple[float, float]]]:
    """Read trailing 5 years of raw sub-score values per (segment, name).

    Returns a dict keyed by (segment, sub_score_name) with a list of
    (unix_timestamp, raw_value) pairs for rolling normalization.

    When `as_of` is provided, rows are restricted to
    `computed_at <= as_of` for point-in-time backtests.
    """
    cutoff = until - timedelta(days=1825)
    upper = min(until, as_of) if as_of is not None else until
    out: dict[tuple[str, str], list[tuple[float, float]]] = {}
    with session_scope(factory) as session:
        rows = session.execute(
            select(
                SubScoreHistory.segment,
                SubScoreHistory.sub_score_name,
                SubScoreHistory.computed_at,
                SubScoreHistory.raw_value,
            )
            .where(SubScoreHistory.computed_at >= cutoff)
            .where(SubScoreHistory.computed_at < upper)
            .where(SubScoreHistory.raw_value.is_not(None))
            .order_by(SubScoreHistory.computed_at.asc())
        ).all()
    for seg, name, comp_at, raw in rows:
        ts = comp_at.timestamp()
        out.setdefault((seg, name), []).append((ts, raw))
    return out


def run(
    *,
    settings: Settings | None = None,
    dry_run: bool = False,
    factory: sessionmaker | None = None,
    now: datetime | None = None,
    skip_prune: bool = False,
    ontology_world: Any | None = None,
    as_of: datetime | None = None,
) -> RunReport:
    """Rebuild the scores table for all segments × horizons.

    Args:
        settings: defaults to get_settings() if None.
        dry_run: if True, writes to /tmp/bottlewatch-dry.db.
        factory: sessionmaker (test hook; defaults to one built
            from `settings.database_url`).
        now: the reference timestamp for "now". Defaults to utcnow().
        skip_prune: if True, do not delete old score_history rows.
        ontology_world: an optional pre-loaded `owlready2.World`.
            When None, the job attempts `load_ontology_world()`
            against the default ABox path. A missing ABox or
            missing owlready2 produces a `world=None` and the
            formula falls back to the seed value for
            `geo_concentration` (preserving M2 stopgap behavior).
        as_of: point-in-time recompute boundary. When provided,
            signals and history are filtered to data available on or
            before `as_of`. Production daily runs should leave this
            as None.
    """
    settings = settings or get_settings()
    started = now or datetime.now(tz=timezone.utc)
    # started is tz-aware; DB-persisted naive_now is naive UTC
    if started.tzinfo:
        naive_now = started.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        naive_now = started

    # Point-in-time runs use as_of as the effective "now".
    effective_now = as_of if as_of is not None else naive_now
    if effective_now.tzinfo:
        effective_now = effective_now.astimezone(timezone.utc).replace(tzinfo=None)

    if factory is None:
        db_url = _dry_run_url(settings.database_url) if dry_run else settings.database_url
        factory = make_session_factory(make_engine(db_url))

    _LOGGER.info(
        "recompute: using regime thresholds %s (frozen since %s)",
        THRESHOLDS_VERSION,
        THRESHOLDS_FROZEN_SINCE or "unknown",
    )
    _LOGGER.info(
        "recompute: using score bands %s (frozen since %s)",
        BANDS_VERSION,
        BANDS_FROZEN_SINCE or "unknown",
    )

    segments = known_segments()
    horizons = settings.score_horizons
    if not segments:
        return RunReport(
            started_at=started,
            finished_at=datetime.now(tz=timezone.utc),
            dry_run=dry_run,
            rows_written=0,
            segments_scored=0,
            no_data_count=0,
            detail="no segments in scoring_seed.json",
        )

    # Load HHI source based on feature flag.
    if ontology_world is None:
        ontology_world = load_ontology_world()
    geo_by_segment = _compute_geo_by_segment(settings, ontology_world)

    # Snapshot existing first_computed_at before we delete rows.
    existing = _load_existing_first_computed_at(factory)
    # Load trailing 6mo of score_history for momentum formula.
    score_history = _load_score_history(factory, until=effective_now, as_of=as_of)
    # Load trailing 5y of sub_score_history for rolling normalization.
    sub_score_history = _load_sub_score_history(factory, until=effective_now, as_of=as_of)

    since = effective_now - timedelta(days=_LOOKBACK_DAYS)
    signals_by_segment = _load_signals_by_segment(factory, since=since, until=effective_now, as_of=as_of)

    # Pre-compute per-segment dynamic `demand_signal` and
    # `lead_time_growth` (raw values + source keys).
    demand_signal_by_segment = _compute_demand_signal_by_segment(signals_by_segment)
    lead_time_by_segment = _compute_lead_time_by_segment(signals_by_segment)

    new_rows: list[dict[str, Any]] = []
    history_rows: list[dict[str, Any]] = []
    sub_score_rows: list[dict[str, Any]] = []
    no_data_count = 0
    for segment in segments:
        seg_signals = signals_by_segment.get(segment, [])
        segment_result: ScoreResult | None = None
        for horizon in horizons:
            first_at = existing.get((segment, horizon))
            b_hist = score_history.get((segment, horizon), [])
            result = compute_segment_score(
                segment,
                horizon,
                signals=seg_signals,  # type: ignore[arg-type]
                b_history=b_hist,
                first_computed_at=first_at,
                now=effective_now,
                geo_concentration=geo_by_segment.get(segment),
                demand_signal=demand_signal_by_segment.get(segment),
                lead_time_growth=lead_time_by_segment.get(segment),
                normalization_mode=settings.score_normalization_mode,
                sub_score_history=sub_score_history,
            )
            segment_result = result
            if result.regime.value == "NO_DATA":
                no_data_count += 1
            new_rows.append(result.to_persisted())
            history_rows.append(
                {
                    "segment": segment,
                    "horizon": horizon,
                    "b": result.score,
                    "momentum": result.momentum,
                    "regime": result.regime.value,
                    "normalization_mode": settings.score_normalization_mode,
                    "computed_at": effective_now,
                }
            )
        if segment_result is not None:
            for name, raw in segment_result.raw_sub_scores.items():
                # Use the normalized value from sub_scores (which is never None
                # because the normalizer substitutes 0.5 for missing values).
                normalized = segment_result.sub_scores[name]
                sub_score_rows.append(
                    {
                        "segment": segment,
                        "sub_score_name": name,
                        "computed_at": effective_now,
                        "raw_value": raw,
                        "normalized_value": normalized,
                        "normalization_mode": segment_result.normalization_mode,
                        # Band bounds are not returned by the normalizer today;
                        # leave them null. They can be added later if needed for audit.
                        "band_min": None,
                        "band_max": None,
                        "history_span_days": None,
                    }
                )

    # Atomic rebuild.
    with session_scope(factory) as session:
        if not skip_prune:
            prune_cutoff = naive_now - timedelta(days=_RETENTION_DAYS)
            session.execute(delete(ScoreHistory).where(ScoreHistory.computed_at < prune_cutoff))
            session.execute(delete(SubScoreHistory).where(SubScoreHistory.computed_at < prune_cutoff))
        session.execute(delete(Score))
        session.bulk_insert_mappings(Score, new_rows)  # type: ignore[arg-type]
        session.bulk_insert_mappings(ScoreHistory, history_rows)  # type: ignore[arg-type]
        session.bulk_insert_mappings(SubScoreHistory, sub_score_rows)  # type: ignore[arg-type]

    finished = datetime.now(tz=timezone.utc)
    _append_log(
        settings.refresh_log_path,
        {
            "ts": started.isoformat(),
            "source": "score_recompute",
            "status": "OK",
            "rows_written": len(new_rows),
            "detail": f"{len(segments)} segments x {len(horizons)} horizons; {no_data_count} NO_DATA; norm={settings.score_normalization_mode}; geo={settings.geo_concentration_source}",
            "dry_run": dry_run,
        },
    )
    _LOGGER.info(
        "recompute: %d rows (%d segments, %d NO_DATA) in %s",
        len(new_rows),
        len(segments),
        no_data_count,
        dry_db_label(dry_run),
    )
    return RunReport(
        started_at=started,
        finished_at=finished,
        dry_run=dry_run,
        rows_written=len(new_rows),
        segments_scored=len(segments),
        no_data_count=no_data_count,
    )


def dry_db_label(dry_run: bool) -> str:
    return "tmp DB" if dry_run else "production DB"


def _append_log(path: Path, payload: dict[str, Any]) -> None:
    """Append a JSONL line to the refresh log. Same shape as
    `refresh_daily._append_log` so the dashboard reads both
    uniformly.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(payload) + "\n")
    except OSError as e:
        # Logging should never crash a job.
        _LOGGER.warning("could not append to %s: %s", path, e)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bottlewatch-recompute",
        description="Recompute the scores table from the current signals + seed JSON.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write to /tmp/bottlewatch-dry.db instead of the real DB.",
    )
    parser.add_argument(
        "--backfill-since",
        type=date.fromisoformat,
        default=None,
        help="Compute monthly scores from this date (YYYY-MM-DD) to today.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        if args.backfill_since:
            # Backfill loop: iterate from backfill_since to today,
            # once per month (on the 1st of each month).
            start_date = args.backfill_since
            today = date.today()
            current = start_date.replace(day=1)

            while current <= today:
                now_dt = datetime.combine(current, datetime.min.time(), tzinfo=timezone.utc)
                print(f"Backfilling {current.isoformat()}...")
                run(dry_run=args.dry_run, now=now_dt, skip_prune=True)

                # Advance to next month
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)

            # Final run for "now" to ensure the current `scores` table is correct
            # and includes all latest signals.
            print("Finalizing current scores...")
            report = run(dry_run=args.dry_run)
        else:
            report = run(dry_run=args.dry_run)
    except SQLAlchemyError as e:
        print(f"fatal: database error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 - catch-all at the CLI boundary
        print(f"fatal: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    for line in report.to_lines():
        print(line)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
