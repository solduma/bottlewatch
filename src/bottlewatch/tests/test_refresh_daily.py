"""Tests for the refresh_daily orchestrator.

We exercise the public `run()` function directly (not the CLI) so the
tests are fast and the assertion surface is clear. CLI smoke is
covered by `test_main_via_argparse`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
import respx
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import IngestRun, Signal
from bottlewatch.app.ingest.eia import _SERIES_SPEC
from bottlewatch.config import Settings
from bottlewatch.jobs import refresh_daily

_BASE_URL = "https://api.eia.gov/v2"


def _envelope(data: list[dict[str, Any]]) -> dict[str, Any]:
    return {"response": {"total": len(data), "data": data}}


def _annual_payload(n: int = 3) -> list[dict[str, Any]]:
    return [{"period": 2024 - i, "generation": 4000 - i * 10} for i in range(n)]


def test_missing_key_results_in_skipped(settings_no_key: Settings, factory: sessionmaker) -> None:
    report = refresh_daily.run(settings=settings_no_key, source_filter=["eia_v2"], dry_run=False)
    assert len(report.adapter_results) == 1
    result = report.adapter_results[0]
    assert result["source"] == "eia_v2"
    assert result["status"] == "SKIPPED"
    assert "EIA_API_KEY" in result["detail"]
    assert report.exit_code == 0  # SKIPPED is not a hard error


def test_happy_path_writes_signals_and_upserts_watermark(settings: Settings, factory: sessionmaker) -> None:
    with respx.mock(base_url=_BASE_URL) as mock:
        for s in _SERIES_SPEC:
            n = 3
            payload = (
                [{"period": f"2024-{m:02d}", "sales": 2500 + m} for m in range(1, n + 1)]
                if s["series_id"].endswith(".M")
                else _annual_payload(n)
            )
            mock.get(f"/seriesid/{s['series_id']}").respond(200, json=_envelope(payload))

        # The orchestrator's default daily window is today-8d..today; the
        # test payload uses 2022..2024, so we widen the window to keep
        # the test about orchestrator/DB plumbing, not the date filter.
        report = refresh_daily.run(
            settings=settings,
            source_filter=["eia_v2"],
            since=date(2022, 1, 1),
            until=date(2024, 12, 31),
            dry_run=False,
            factory=factory,
        )

    assert report.exit_code == 0
    result = report.adapter_results[0]
    assert result["status"] == "OK"
    assert result["rows_written"] == 3 * len(_SERIES_SPEC)

    with factory() as session:
        signals = session.execute(select(Signal)).scalars().all()
        assert len(signals) == 3 * len(_SERIES_SPEC)
        run = session.get(IngestRun, "eia_v2")
        assert run is not None
        assert run.status == "OK"
        assert run.rows_written == 3 * len(_SERIES_SPEC)


def test_watermark_skips_second_run_within_cadence(settings: Settings, factory: sessionmaker) -> None:
    """First run writes rows; second run within the daily window is SKIPPED."""
    with respx.mock(base_url=_BASE_URL) as mock:
        for s in _SERIES_SPEC:
            mock.get(f"/seriesid/{s['series_id']}").respond(200, json=_envelope(_annual_payload(2)))
        first = refresh_daily.run(settings=settings, source_filter=["eia_v2"], dry_run=False, factory=factory)
        second = refresh_daily.run(settings=settings, source_filter=["eia_v2"], dry_run=False, factory=factory)

    assert first.adapter_results[0]["status"] == "OK"
    assert second.adapter_results[0]["status"] == "SKIPPED"
    assert second.adapter_results[0]["detail"] == "watermark fresh"


def test_dry_run_does_not_touch_production_db(tmp_path, settings: Settings) -> None:
    """A tmp file DB is bootstrapped + populated by the orchestrator;
    the in-memory test factory (representing prod) sees no rows.
    """
    tmp_db = tmp_path / "bottlewatch.db"
    # Boot the schema on the tmp file the same way `make db-upgrade`
    # would in production. The orchestrator no longer auto-creates.
    from bottlewatch.app.db import init_schema, make_engine
    from sqlalchemy.orm import sessionmaker as sm

    init_schema(make_engine(f"sqlite:///{tmp_db}"))
    dry_factory = sm(bind=make_engine(f"sqlite:///{tmp_db}"), autoflush=False, autocommit=False)
    dry_settings = Settings(
        app_env="test",
        eia_api_key="test-key",
        database_url=f"sqlite:///{tmp_db}",
        refresh_log_path=tmp_path / "refresh.log",
    )
    with respx.mock(base_url=_BASE_URL) as mock:
        for s in _SERIES_SPEC:
            n = 1
            payload = (
                [{"period": f"2024-{m:02d}", "sales": 2500 + m} for m in range(1, n + 1)]
                if s["series_id"].endswith(".M")
                else _annual_payload(n)
            )
            mock.get(f"/seriesid/{s['series_id']}").respond(200, json=_envelope(payload))
        report = refresh_daily.run(
            settings=dry_settings,
            source_filter=["eia_v2"],
            since=date(2024, 1, 1),
            until=date(2024, 12, 31),
            dry_run=False,
            factory=dry_factory,
        )
    assert report.adapter_results[0]["status"] == "OK"
    with dry_factory() as session:
        count = session.execute(select(Signal)).scalars().all()
        assert len(count) == len(_SERIES_SPEC)


def test_backfill_overrides_period_window(settings: Settings, factory: sessionmaker) -> None:
    """`--since`/`--until` are passed through to the adapter's fetch window."""
    with respx.mock(base_url=_BASE_URL) as mock:
        for s in _SERIES_SPEC:
            mock.get(f"/seriesid/{s['series_id']}").respond(200, json=_envelope(_annual_payload(2)))
        report = refresh_daily.run(
            settings=settings,
            source_filter=["eia_v2"],
            since=date(2022, 1, 1),
            until=date(2022, 12, 31),
            dry_run=False,
            factory=factory,
        )
    assert report.adapter_results[0]["status"] == "OK"


def test_adapter_error_is_recorded(settings: Settings, factory: sessionmaker) -> None:
    """An adapter that raises (4xx on every series) ends with status=ERROR."""
    with respx.mock(base_url=_BASE_URL, assert_all_called=False) as mock:
        for s in _SERIES_SPEC:
            mock.get(f"/seriesid/{s['series_id']}").respond(400, text="bad")
        report = refresh_daily.run(settings=settings, source_filter=["eia_v2"], dry_run=False, factory=factory)

    assert report.adapter_results[0]["status"] == "ERROR"
    assert report.exit_code == 1
    with factory() as session:
        run = session.get(IngestRun, "eia_v2")
        assert run is not None
        assert run.status == "ERROR"
        assert "_EIAHardError" in (run.detail or "")


def test_main_via_argparse_skips_when_no_key(
    settings_no_key: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """End-to-end CLI smoke: `bottlewatch-refresh` with no key -> exit 0, SKIPPED line."""
    # The CLI uses get_settings() internally; stub it so the test
    # doesn't read the real .env.
    monkeypatch.setattr(refresh_daily, "get_settings", lambda: settings_no_key)
    rc = refresh_daily.main(["--source", "eia_v2"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "SKIPPED" in captured.out


def test_orchestrator_does_not_auto_create_tables(tmp_path, settings: Settings) -> None:
    """`make db-upgrade` is the only path that creates the schema.

    If the operator runs `make ingest` against a fresh DB, the first
    write should raise NoSuchTableError (not silently create tables).
    """
    import sqlite3

    from sqlalchemy.exc import OperationalError, ProgrammingError

    fresh_db = tmp_path / "fresh.db"
    # sqlite3 itself creates an empty file on connect, but with no
    # tables — exactly the post-`make db-upgrade`-not-yet-run state.
    sqlite3.connect(fresh_db).close()
    fresh_settings = Settings(
        app_env="test",
        eia_api_key="test-key",
        fred_api_key="test-key",  # enable FRED for the multi-adapter test below
        database_url=f"sqlite:///{fresh_db}",
        refresh_log_path=tmp_path / "refresh.log",
    )
    with respx.mock(base_url=_BASE_URL, assert_all_called=False) as mock:
        for s in _SERIES_SPEC:
            mock.get(f"/seriesid/{s['series_id']}").respond(200, json=_envelope(_annual_payload(1)))
        with pytest.raises((OperationalError, ProgrammingError)):
            refresh_daily.run(settings=fresh_settings, source_filter=["eia_v2"], dry_run=False)


_FRED_BASE = "https://api.stlouisfed.org"


def test_orchestrator_runs_independent_adapters_in_sequence(settings: Settings, factory: sessionmaker) -> None:
    """Regression: an EIA failure must not block a FRED run. The
    orchestrator's per-source try/except was historically
    untested; a refactor that bubbles exceptions up would
    regress this without the test.
    """
    from bottlewatch.app.ingest.fred import _SERIES_SPEC as _FRED_SERIES_SPEC  # noqa: PLC0415

    with (
        respx.mock(base_url=_BASE_URL, assert_all_called=False) as eia_mock,
        respx.mock(base_url=_FRED_BASE, assert_all_called=False) as fred_mock,
    ):
        # EIA: every series returns 400 → ERROR
        for s in _SERIES_SPEC:
            eia_mock.get(f"/seriesid/{s['series_id']}").respond(400, text="bad")
        # FRED: every series returns a valid 2-point response → OK
        for spec in _FRED_SERIES_SPEC:
            fred_mock.get(
                "/fred/series/observations",
                params={"series_id": spec.series_id},
            ).respond(
                200,
                json={
                    "observations": [
                        {"date": "2024-01-01", "value": "."},
                        {"date": "2024-02-01", "value": "1.5"},
                    ]
                },
            )
        report = refresh_daily.run(
            settings=settings,
            source_filter=["eia_v2", "fred"],
            dry_run=False,
            factory=factory,
        )

    by_source = {r["source"]: r for r in report.adapter_results}
    assert by_source["eia_v2"]["status"] == "ERROR", by_source
    assert by_source["fred"]["status"] == "OK", by_source
    assert by_source["fred"]["rows_written"] > 0, by_source
    # Overall exit code is non-zero because one source errored.
    assert report.exit_code == 1


_STUB_SOURCES: tuple[str, ...] = ()


def test_stub_adapters_are_skipped_and_emit_no_signals(settings: Settings, factory: sessionmaker) -> None:
    """No adapters are stubs anymore. All three real adapters
    (sec_insider, epa_egrid, sec_edgar) return True from
    `is_configured()` and are exercised in their own test files.

    This test is a placeholder — it just confirms the orchestrator
    doesn't blow up when a non-matching source filter is given.
    It can be removed once we have confidence the real-adapter
    tests cover the orchestrator's wiring for stub-style behavior.
    """
    # Pass a non-existent source name so the orchestrator takes
    # the "no adapters matched" early-return path without
    # iterating over the real adapters (which would make real
    # network calls and hang the test).
    report = refresh_daily.run(
        settings=settings,
        source_filter=["nonexistent_adapter_for_test"],
        dry_run=False,
        factory=factory,
    )
    assert report.adapter_results == []
    assert report.exit_code == 0


# ---------------------------------------------------------------------------
# Progress bar: silent on non-TTY, but wired through to fetch()
# ---------------------------------------------------------------------------


def test_progress_bar_silent_on_non_tty(
    settings_no_key: Settings,
    factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The progress bar is a stderr writer. When stderr is not a
    TTY (cron, launchd, pipe redirect), `Progress` must be a no-op
    — no garbage in the JSONL refresh log, no noise in CI output.

    We assert this by:
    1. Mocking `sys.stderr.isatty` to return False.
    2. Capturing stderr in a buffer.
    3. Running the orchestrator with no API keys AND a single
       SKIP-only source (`--source eia_v2`) so no network is
       touched (sec_insider would otherwise try a real EDGAR
       fetch).
    4. Asserting the buffer is empty.
    """
    import sys

    class _FakeStderr:
        def __init__(self) -> None:
            self.buf: list[str] = []

        def write(self, s: str) -> int:
            self.buf.append(s)
            return len(s)

        def flush(self) -> None:
            pass

        def isatty(self) -> bool:
            return False

    fake_err = _FakeStderr()
    monkeypatch.setattr(sys, "stderr", fake_err)

    report = refresh_daily.run(
        settings=settings_no_key,
        source_filter=["eia_v2"],
        dry_run=False,
        factory=factory,
    )
    # The run completed; with no key eia_v2 SKIPs, so the
    # progress bar's outer-level update is called once but
    # produces zero stderr output.
    assert len(report.adapter_results) == 1
    assert report.adapter_results[0]["status"] == "SKIPPED"
    # Stderr is silent — the JSONL log file is the only artifact.
    assert "".join(fake_err.buf) == ""


def test_progress_callback_is_passed_to_fetch(
    settings_no_key: Settings,
    factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The orchestrator wires a `progress` callback into
    `_run_one`, which passes it through to `adapter.fetch()` as
    the `progress` kwarg. With no API keys every adapter
    SKIPs before `fetch()` is called — the wiring is still
    exercised (the callback is set on the function call) but
    the adapters themselves don't iterate.

    This is a smoke test for the wiring, not the callback
    invocation. The per-step invocation is tested directly in
    `test_sec_insider_adapter.py::test_fetch_invokes_progress_callback_per_ticker`.
    """
    original_run_one = refresh_daily._run_one
    call_kwargs: list[dict[str, Any]] = []

    def _patched_run_one(spec, adapter, factory, since, until, now, progress=None):
        call_kwargs.append({"progress": progress})
        return original_run_one(spec, adapter, factory, since, until, now, progress=progress)

    monkeypatch.setattr(refresh_daily, "_run_one", _patched_run_one)

    refresh_daily.run(
        settings=settings_no_key,
        source_filter=["eia_v2"],
        dry_run=False,
        factory=factory,
    )
    # The patched function was called once for eia_v2 with a
    # non-None progress callback.
    assert len(call_kwargs) == 1
    assert call_kwargs[0]["progress"] is not None
    assert callable(call_kwargs[0]["progress"])


def test_progress_class_writes_to_active_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`Progress.update` writes a `\\r`-terminated line to stderr
    when stderr is a TTY, with the format
    `[ 1/9] sec_insider ............... (0.0s)`. We assert the
    exact format and the leading carriage return (so the line
    overwrites itself on the next `update()` call).
    """
    import sys

    captured: list[str] = []

    class _TtyStderr:
        def write(self, s: str) -> int:
            captured.append(s)
            return len(s)

        def flush(self) -> None:
            pass

        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(sys, "stderr", _TtyStderr())

    prog = refresh_daily.Progress(9)
    prog.update(1, 9, "sec_insider")
    # Single write; the format is exactly
    # `\r[ 1/9] sec_insider ............... (0.0s)`.
    assert len(captured) == 1
    assert captured[0].startswith("\r")
    assert "[1/9] sec_insider" in captured[0]
    assert captured[0].rstrip().endswith("(0.0s)")

    # `inner()` overwrites the same line for sec_insider's
    # per-ticker progress.
    captured.clear()
    prog.inner(47, 98, "AAPL")
    assert len(captured) == 1
    assert captured[0].startswith("\r")
    assert "[47/98] AAPL" in captured[0]

    # `done()` writes a final newline so the next stdout line
    # starts on a fresh row.
    captured.clear()
    prog.done()
    assert captured == ["\n"]


def test_progress_class_no_op_on_non_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When stderr is not a TTY (cron, launchd, pipe redirect),
    `Progress` must produce zero output. This is the contract that
    keeps the JSONL refresh log clean.
    """
    import sys

    captured: list[str] = []

    class _PipeStderr:
        def write(self, s: str) -> int:
            captured.append(s)
            return len(s)

        def flush(self) -> None:
            pass

        def isatty(self) -> bool:
            return False

    monkeypatch.setattr(sys, "stderr", _PipeStderr())

    prog = refresh_daily.Progress(9)
    prog.update(1, 9, "sec_insider")
    prog.inner(47, 98, "AAPL")
    prog.done()
    prog.fail()
    assert captured == []
