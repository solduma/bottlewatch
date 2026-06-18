"""Daily refresh orchestrator.

Console entry point: `bottlewatch-refresh` (declared in
pyproject.toml's [project.scripts]). Behaviour per the M1 plan §8:

1. Load Settings (env + .env).
2. Build the SQLAlchemy engine. The schema is owned by alembic
   (`make db-upgrade`); the orchestrator does not create tables. If
   the tables are missing, the first write will raise NoSuchTableError
   with a clear message.
3. For each registered adapter:
   - Read `ingest_runs.last_ingested_at` (the watermark).
   - If the watermark is fresh (< cadence_min_interval) AND the
     prior run was OK, **skip**.
   - Else, compute the period window (default: yesterday for daily,
     etc.) and call `adapter.fetch(...)`.
   - Classify the result: OK / SKIPPED / ERROR. SKIPPED = the
     adapter's `is_configured()` returned False but `fetch()`
     returned []. ERROR = exception. OK = rows came back.
   - Bulk-insert into `signals`; upsert `ingest_runs`.
   - Append a JSONL line to the refresh log.
4. Exit code: 0 if no ERROR, 1 if any adapter ERRORed, 2 for
   config / DB-unreachable errors.

CLI flags:
- --dry-run        : use a /tmp/... DB, do not touch production.
- --source NAME    : only run the named adapter (repeatable).
- --since YYYY-MM-DD : override the period_start for backfills.
- --until YYYY-MM-DD : mirror of --since.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import (
    IngestRun,
    Signal,
    make_engine,
    make_session_factory,
    session_scope,
)
from bottlewatch.app.ingest import Adapter, AdapterSpec, RawSignal, get_registry
from bottlewatch.app.ingest.base import ProgressCallback, quiet_httpx_request_log
from bottlewatch.config import Settings, get_settings

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Progress bar
# ---------------------------------------------------------------------------


class Progress:
    """Single-line stderr progress indicator for `make ingest`.

    Two-level reporting so the user can tell which adapter is
    running and where the long one (`sec_insider`) is in its
    inner loop:

        [ 1/9] eia_v2 ........... SKIPPED (watermark fresh)
        [ 2/9] sec_insider ...... [ 47/98] AAPL     (51.2s)

    The line is overwritten in place via `\\r`; `done()` clears
    it. On a non-TTY stderr (cron, launchd, pipe redirect), the
    class is a silent no-op — the user gets clean JSONL log
    lines in `data/cache/refresh.log` instead.

    No external dependency. Adding rich/tqdm would be ~30 lines
    of saved code but at the cost of a new dep; this 50-line
    utility is the minimum that solves the problem.
    """

    def __init__(self, total: int) -> None:
        self._total = total
        self._started = datetime.now(tz=timezone.utc)
        self._active = sys.stderr.isatty()

    def update(self, current: int, total: int, label: str) -> None:
        """Outer-level update: `current` is the adapter index (1-based),
        `total` is the number of adapters, `label` is the adapter name.
        """
        if not self._active:
            return
        elapsed = (datetime.now(tz=timezone.utc) - self._started).total_seconds()
        line = f"[{current:>{len(str(self._total))}}/{self._total}] {label}"
        # Pad to a fixed width so the line clears reliably when
        # `label` shrinks (e.g. sec_insider from "eia_electric" →
        # "sec_insider" doesn't leave trailing characters).
        line = f"{line:<24} ..."
        sys.stderr.write(f"\r{line} ({elapsed:.1f}s)")
        sys.stderr.flush()

    def inner(self, current: int, total: int, label: str) -> None:
        """Inner-level update: used by sec_insider to show its
        per-ticker progress. Combines with the outer-level line.
        """
        if not self._active:
            return
        elapsed = (datetime.now(tz=timezone.utc) - self._started).total_seconds()
        # Use 4-space padding for inner total (e.g. " 47/98").
        line = f"               [{current:>{len(str(total))}}/{total}] {label}"
        sys.stderr.write(f"\r{line} ({elapsed:.1f}s)")
        sys.stderr.flush()

    def done(self) -> None:
        """Write a final newline so the next stdout line is clean."""
        if not self._active:
            return
        sys.stderr.write("\n")
        sys.stderr.flush()

    def fail(self) -> None:
        """Same as `done()` — call from the ERROR path to clear the
        line so the orchestrator's `to_lines()` output starts on a
        fresh line.
        """
        self.done()


# 730 days = 2 years. EIA v2 returns monthly retail-sales data
# (`ELEC.SALES.*.M`) inside the same adapter as daily series; the
# 7-day revision window was too tight to capture monthly observations.
# The per-row filter in each adapter's `_parse_series` still bounds
# the result to whatever the user actually wants via --since/--until.
_DEFAULT_DAILY_LOOKBACK_DAYS = 730  # EIA revises last 7d; +723d for monthly series


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class RunReport:
    """Summary of one orchestrator run. Returned by `run()` and printed at the end."""

    started_at: datetime
    finished_at: datetime
    dry_run: bool
    source_filter: list[str]
    adapter_results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        statuses = {r["status"] for r in self.adapter_results}
        if "ERROR" in statuses:
            return 1
        return 0

    def to_lines(self) -> list[str]:
        """Human-readable one-liner per adapter, plus a footer."""
        lines = []
        for r in self.adapter_results:
            tail = f"  ({r.get('detail', '')})" if r.get("detail") else ""
            lines.append(f"  {r['source']:<10} {r['status']:<8} {r.get('rows_written', 0)} rows{tail}")
        elapsed = (self.finished_at - self.started_at).total_seconds()
        lines.append(f"  finished in {elapsed:.1f}s")
        return lines


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


def _window_for(cadence: Any, since: date | None, until: date | None) -> tuple[date, date]:
    """Compute the fetch period for an adapter.

    Honors the user's --since/--until if provided; otherwise defaults
    to a window that matches the cadence. EIA's 7-day revision window
    means a daily fetch re-pulls 8 days even when running "today".
    """
    today = date.today()
    if until is None:
        until = today
    if since is not None:
        return since, until
    if cadence.label == "daily":
        return today - timedelta(days=_DEFAULT_DAILY_LOOKBACK_DAYS), until
    if cadence.label == "weekly":
        return today - timedelta(days=14), until  # 1 revision week + 1
    if cadence.label == "monthly":
        # First of the previous month through today
        first_of_this_month = today.replace(day=1)
        last_month_end = first_of_this_month - timedelta(days=1)
        return last_month_end.replace(day=1), until
    return today - timedelta(days=_DEFAULT_DAILY_LOOKBACK_DAYS), until


def _watermark_fresh(
    last_ingested_at: datetime | None,
    cadence: Any,
    now: datetime,
) -> bool:
    """True if the source ran successfully within the cadence window.

    `last_ingested_at` is stored as naive UTC (matching the column
    type); `now` is tz-aware. Normalize both to the same form before
    the delta.
    """
    if last_ingested_at is None:
        return False
    if now.tzinfo is not None and last_ingested_at.tzinfo is None:
        last_ingested_at = last_ingested_at.replace(tzinfo=timezone.utc)
    elif now.tzinfo is None and last_ingested_at.tzinfo is not None:
        now = now.replace(tzinfo=None)
    delta = now - last_ingested_at
    return delta < timedelta(days=cadence.min_interval_days)


def _write_signals(session, signals: list[RawSignal]) -> None:
    """Bulk-insert signals. We do not dedupe on (source, source_id, observed_at)
    here because EIA revises historical values; the unique-key story is a
    downstream upsert for the scoring job in M2+, not the ingest job.
    """
    if not signals:
        return
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)  # store naive UTC
    rows = [
        Signal(
            segment=s.segment,
            subsegment=s.subsegment,
            signal_name=s.signal_name,
            value_num=s.value_num,
            value_text=s.value_text,
            unit=s.unit,
            geography=s.geography,
            source=s.source,
            source_id=s.source_id,
            observed_at=s.observed_at,
            released_at=s.released_at,
            ingested_at=now,
            tickers=s.tickers,
        )
        for s in signals
    ]
    session.add_all(rows)


def _upsert_ingest_run(
    session,
    source: str,
    status: str,
    rows_written: int,
    detail: str,
) -> None:
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    existing = session.get(IngestRun, source)
    if existing is None:
        session.add(
            IngestRun(
                source=source,
                last_ingested_at=now,
                rows_written=rows_written,
                status=status,
                detail=detail,
            )
        )
        return
    existing.last_ingested_at = now
    existing.rows_written = rows_written
    existing.status = status
    existing.detail = detail


def _append_log(log_path: Path, payload: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")


def _run_one(
    spec: AdapterSpec,
    adapter: Adapter,
    factory: sessionmaker,
    since: date | None,
    until: date | None,
    now: datetime,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run one adapter, write its signals + watermark, return a status dict.

    `progress` is the orchestrator's inner-progress callback
    (e.g. `Progress.inner`). It's passed through to
    `adapter.fetch()` for adapters that have a meaningful inner
    loop (currently only `sec_insider`).
    """
    # The configured-check is a no-network gate. We do it before
    # touching the DB so a missing key (e.g. on a dev box) doesn't
    # require the schema to exist. SKIPPED-no-key is a benign state.
    ok, reason = adapter.is_configured()
    if not ok:
        return {
            "source": spec.name,
            "status": "SKIPPED",
            "rows_written": 0,
            "detail": reason,
        }
    period_start, period_end = _window_for(spec.cadence, since, until)
    with session_scope(factory) as session:
        prev = session.get(IngestRun, spec.name)
        last_ok_at = prev.last_ingested_at if (prev and prev.status == "OK") else None
        if _watermark_fresh(last_ok_at, spec.cadence, now):
            return {
                "source": spec.name,
                "status": "SKIPPED",
                "rows_written": 0,
                "detail": "watermark fresh",
            }
    try:
        signals = adapter.fetch(period_start, period_end, progress=progress)
    except Exception as e:  # noqa: BLE001 - report and continue
        _LOGGER.exception("adapter %s raised", spec.name)
        with session_scope(factory) as session:
            _upsert_ingest_run(session, spec.name, "ERROR", 0, f"{type(e).__name__}: {e}")
        return {
            "source": spec.name,
            "status": "ERROR",
            "rows_written": 0,
            "detail": f"{type(e).__name__}: {e}",
        }

    if not signals:
        # Configured (gated above) but the source returned no rows.
        with session_scope(factory) as session:
            _upsert_ingest_run(session, spec.name, "OK", 0, "no rows")
        return {"source": spec.name, "status": "OK", "rows_written": 0, "detail": "no rows"}

    with session_scope(factory) as session:
        _write_signals(session, signals)
        _upsert_ingest_run(session, spec.name, "OK", len(signals), "")
    return {"source": spec.name, "status": "OK", "rows_written": len(signals), "detail": ""}


def run(
    *,
    settings: Settings | None = None,
    dry_run: bool = False,
    source_filter: list[str] | None = None,
    since: date | None = None,
    until: date | None = None,
    factory: sessionmaker | None = None,
) -> RunReport:
    """The public entry point. All side effects live here.

    `factory` is a test hook: pass an already-built sessionmaker bound
    to a known engine (so the test can assert on the same DB the
    orchestrator wrote to). When None, we build one from `settings`.
    """
    settings = settings or get_settings()
    source_filter = source_filter or []

    if factory is None:
        db_url = settings.database_url
        if dry_run:
            db_url = f"sqlite:///{Path('/tmp/bottlewatch-dry.db')}"

        engine = make_engine(db_url)
        factory = make_session_factory(engine)
        # We do NOT auto-create tables here. Operators must run
        # `make db-upgrade` first; if the schema is missing the first
        # write will fail with a clear NoSuchTableError. This keeps
        # alembic as the single source of truth for the schema.

    registry = get_registry()
    if source_filter:
        registry = [s for s in registry if s.name in source_filter]
        if not registry:
            _LOGGER.error("no adapters matched --source filter %s", source_filter)
            return RunReport(
                started_at=datetime.now(tz=timezone.utc),
                finished_at=datetime.now(tz=timezone.utc),
                dry_run=dry_run,
                source_filter=source_filter,
                adapter_results=[],
            )

    started = datetime.now(tz=timezone.utc)
    results: list[dict[str, Any]] = []
    prog = Progress(len(registry))
    for i, spec in enumerate(registry, 1):
        prog.update(i, len(registry), spec.name)
        adapter = spec.factory(settings)  # type: ignore[call-arg]
        result = _run_one(spec, adapter, factory, since, until, started, prog.inner)
        results.append(result)
        _append_log(
            settings.refresh_log_path,
            {
                "ts": started.isoformat(),
                "source": result["source"],
                "status": result["status"],
                "rows_written": result["rows_written"],
                "detail": result["detail"],
                "dry_run": dry_run,
            },
        )
        if result["status"] == "ERROR":
            # The line stays put for ERROR; caller will print to
            # stdout on a fresh line.
            prog.fail()
    prog.done()
    finished = datetime.now(tz=timezone.utc)
    return RunReport(
        started_at=started,
        finished_at=finished,
        dry_run=dry_run,
        source_filter=source_filter,
        adapter_results=results,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bottlewatch-refresh",
        description="Refresh all configured data sources into the bottlewatch DB.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write to /tmp/bottlewatch-dry.db instead of the real DB.",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Only run the named adapter (repeatable). Default: all registered.",
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        default=None,
        help="Override period_start (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--until",
        type=date.fromisoformat,
        default=None,
        help="Override period_end (YYYY-MM-DD).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # httpx logs the full request URL at INFO, which would expose the
    # EIA API key. Drop to WARNING; the orchestrator's structured log
    # line still records the source + status + rows_written.
    quiet_httpx_request_log()
    try:
        report = run(
            dry_run=args.dry_run,
            source_filter=args.source or None,
            since=args.since,
            until=args.until,
        )
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
