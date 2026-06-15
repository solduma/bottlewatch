"""Recompute the materialized `scores` table (M2/M3).

Console entry point: `bottlewatch-recompute` (declared in
pyproject.toml's [project.scripts]). Mirrors `refresh_daily.py`'s
`run()/main()` structure for CLI consistency.

What it does:
1. Read the `signals` table for the latest 24mo of values per
   (segment, signal_name) — enough for the 5y normalize band
   (we only have 2y of data, so the band is the actual range).
2. Prune score_history rows older than 12 months.
3. Load the trailing 6 months of score_history per (segment, horizon)
   to compute real momentum (B').
4. For each of 10 segments in `scoring_seed.json` and each of
   3 horizons, call `score.compute_segment_score(...)`.
5. Atomically rebuild the `scores` table: delete all rows, bulk
   insert the new ones, all in one transaction. The API never
   sees a half-populated state.
6. Append 30 new score_history rows (one per segment × horizon).
7. Append a JSONL line to `data/cache/refresh.log` (same log as
   `refresh_daily.py`, so the dashboard can read both).

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
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import (
    Score,
    ScoreHistory,
    Signal,
    make_engine,
    make_session_factory,
    session_scope,
)
from bottlewatch.app.score import compute_segment_score
from bottlewatch.app.score import extractors
from bottlewatch.app.score.research_values import known_segments
from bottlewatch.config import Settings, get_settings

_LOGGER = logging.getLogger(__name__)

# The recompute job reads the last `_LOOKBACK_DAYS` of signals per
# segment to feed the capacity_tightness extractors. 730d covers
# the longest input the extractors need (24mo of retail_sales_mwh
# for the YoY computation in _data_center_shell_tightness).
_LOOKBACK_DAYS = 730


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
    """Read signals within the window [since, until], grouped by segment.

    When `as_of` is provided, the query is gated on the signal's
    `released_at` (or `ingested_at` when `released_at` is null) and
    on `observed_at <= as_of.date()`. This is the point-in-time path
    used by historical recomputes; the daily production path leaves
    `as_of` as None and loads all signals in the window.

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

    as_of_naive = as_of
    as_of_date = None
    if as_of is not None and as_of.tzinfo is not None:
        as_of_naive = as_of.astimezone(timezone.utc).replace(tzinfo=None)
    if as_of_naive is not None:
        as_of_date = as_of_naive.date()

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
        if as_of_naive is not None:
            # True point-in-time gate: when the source exposes a release
            # date, use it; otherwise fall back to when the row was
            # ingested. `observed_at` is also bounded by the as-of date
            # so forward-dated observations cannot leak into history.
            available_at = func.coalesce(Signal.released_at, Signal.ingested_at)
            stmt = stmt.where(available_at <= as_of_naive).where(Signal.observed_at <= as_of_date)
        return stmt

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
    # Re-sort each segment's signals by observed_at ascending so the
    # extractors that depend on a chronological view (YoY, latest
    # vs prior) see the right ordering.
    for seg_signals in out.values():
        seg_signals.sort(key=lambda r: r.observed_at)
    return out


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


def _compute_geo_by_segment(world: Any | None) -> dict[str, float | None]:
    """Pre-compute HHI for every known segment. Returns a dict
    segment -> HHI (or None when the segment has no role instances
    in the ABox). The recompute job passes this to the formula
    one segment at a time.
    """
    if world is None:
        return {}
    out: dict[str, float | None] = {}
    for segment in known_segments():
        out[segment] = extractors.geo_concentration(segment, world)
    return out


def _compute_demand_signal_by_segment(signals_by_segment: dict[str, list[Any]]) -> dict[str, float | None]:
    """Pre-compute the dynamic `demand_signal` sub-score for every
    known segment. Returns a dict segment -> score (or None when
    the segment has no dynamic extractor in the current data set).

    Mirrors `_compute_geo_by_segment`. Currently only
    `transformers_tnd` has a dynamic demand_signal (FRED `A35SNO`
    electrical equipment new orders). The other segments fall
    back to the static seed value in `research_values`.
    """
    out: dict[str, float | None] = {}
    for segment in known_segments():
        seg_signals = signals_by_segment.get(segment, [])
        out[segment] = extractors.demand_signal(segment, seg_signals)
    return out


def _compute_lead_time_by_segment(signals_by_segment: dict[str, list[Any]]) -> dict[str, float | None]:
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
    out: dict[str, float | None] = {}
    for segment in known_segments():
        seg_signals = signals_by_segment.get(segment, [])
        out[segment] = extractors.lead_time_growth(segment, seg_signals)
    return out


def _load_score_history(factory: sessionmaker, until: datetime) -> dict[tuple[str, str], list[tuple[datetime, float]]]:
    """Read the trailing 7 months of score_history per (segment, horizon) relative to until."""
    cutoff = until - timedelta(days=210)  # 7 months
    out: dict[tuple[str, str], list[tuple[datetime, float]]] = {}
    with session_scope(factory) as session:
        rows = session.execute(
            select(ScoreHistory.segment, ScoreHistory.horizon, ScoreHistory.computed_at, ScoreHistory.b)
            .where(ScoreHistory.computed_at >= cutoff)
            .where(ScoreHistory.computed_at < until)
            .order_by(ScoreHistory.computed_at.asc())
        ).all()
    for seg, hor, comp_at, b in rows:
        if b is not None:
            out.setdefault((seg, hor), []).append((comp_at, b))
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
            signals are gated on `released_at` (or `ingested_at` as
            a fallback) and `observed_at <= as_of.date()`. Production
            daily runs should leave this as None.
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

    # Load ontology (once) and pre-compute per-segment HHI.
    if ontology_world is None:
        ontology_world = load_ontology_world()
    geo_by_segment = _compute_geo_by_segment(ontology_world)

    # Snapshot existing first_computed_at before we delete rows.
    existing = _load_existing_first_computed_at(factory)
    # Load trailing 6mo of score_history for momentum formula.
    score_history = _load_score_history(factory, until=effective_now)

    since = effective_now - timedelta(days=_LOOKBACK_DAYS)
    signals_by_segment = _load_signals_by_segment(factory, since=since, until=effective_now, as_of=as_of)

    # Pre-compute per-segment dynamic `demand_signal` (FRED
    # `A35SNO` for `transformers_tnd`; None for everything else,
    # which falls back to the static seed value).
    demand_signal_by_segment = _compute_demand_signal_by_segment(signals_by_segment)

    # Pre-compute per-segment dynamic `lead_time_growth` (FRED
    # `WPU1321` for `transformers_tnd`; None for everything else,
    # which falls back to the static seed value).
    lead_time_by_segment = _compute_lead_time_by_segment(signals_by_segment)

    new_rows: list[dict[str, Any]] = []
    history_rows: list[dict[str, Any]] = []
    no_data_count = 0
    for segment in segments:
        seg_signals = signals_by_segment.get(segment, [])
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
            )
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
                    "computed_at": effective_now,
                }
            )

    # Atomic rebuild.
    with session_scope(factory) as session:
        if not skip_prune:
            # Prune score_history rows older than 12 months before inserting new ones.
            prune_cutoff = naive_now - timedelta(days=_RETENTION_DAYS)
            session.execute(delete(ScoreHistory).where(ScoreHistory.computed_at < prune_cutoff))
        session.execute(delete(Score))
        session.bulk_insert_mappings(Score, new_rows)  # type: ignore[arg-type]
        session.bulk_insert_mappings(ScoreHistory, history_rows)  # type: ignore[arg-type]

    finished = datetime.now(tz=timezone.utc)
    _append_log(
        settings.refresh_log_path,
        {
            "ts": started.isoformat(),
            "source": "score_recompute",
            "status": "OK",
            "rows_written": len(new_rows),
            "detail": f"{len(segments)} segments x {len(horizons)} horizons; {no_data_count} NO_DATA",
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
