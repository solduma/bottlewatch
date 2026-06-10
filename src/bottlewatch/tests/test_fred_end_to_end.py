"""End-to-end verification that FRED data flows from the adapter
through the refresh orchestrator into the recompute job's score rows.

This is the load-bearing test for `m4-backtest-final.md`'s P1 item:
"Automate `transformers_tnd` with FRED PPI data". If the wiring
breaks (FRED removed from the registry, the wrong series ID, the
orchestrator stops iterating the registry, the recompute job drops
the `ppi_transformers` rows, etc.) the `transformers_tnd` segment
loses its `capacity_tightness` and silently regresses to NO_DATA
once the seed `transformers_tnd` value is overridden.

The test:
1. Mocks the FRED API to return >=14 months of `WPU1321` data with
   rising values (the `_transformer_tightness` extractor needs >=13
   months for a YoY delta).
2. Runs `refresh_daily.run(source_filter=["fred"], ...)` with dates
   relative to `now` so the test is stable over time.
3. Asserts the DB has `ppi_transformers` rows.
4. Runs `recompute_scores.run(...)` and asserts the
   `transformers_tnd` row has a non-None `capacity_tightness` and
   `data_completeness == 1.0`.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import httpx
import respx
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import Score, Signal
from bottlewatch.config import Settings
from bottlewatch.jobs import recompute_scores, refresh_daily

_FRED_BASE_URL = "https://api.stlouisfed.org"


def _settings_with_fred_key(tmp_path: Path) -> Settings:
    """Build a Settings with a known FRED key, independent of .env.

    The default conftest `settings` fixture reads `FRED_API_KEY` from
    the developer's `.env`. To keep this test self-contained, we
    construct a Settings with an explicit key.
    """
    return Settings(
        app_env="test",
        eia_api_key="test-key",
        fred_api_key="test-fred-key",
        database_url="sqlite:///:memory:",
        refresh_log_path=tmp_path / "refresh.log",
    )


def _fred_response_for_series(request: httpx.Request) -> httpx.Response:
    """Route FRED API responses by `series_id` query param.

    Returns 14 monthly observations of `WPU1321` (the series that maps
    to `transformers_tnd`) with values that grow ~3% month-over-month
    so the YoY delta is meaningful. Other series get an empty
    observation set so the test is scoped to `transformers_tnd`.
    """
    sid = request.url.params.get("series_id")
    if sid != "WPU1321":
        return httpx.Response(200, json={"observations": []})

    # 14 months ending today, growing ~3% MoM from a base of 100.
    today = date.today()
    observations: list[dict[str, str]] = []
    value = 100.0
    for months_ago in range(13, -1, -1):
        d = today - timedelta(days=30 * months_ago)
        observations.append({"date": d.isoformat(), "value": f"{value:.2f}"})
        value *= 1.03
    return httpx.Response(200, json={"observations": observations})


def test_fred_end_to_end_produces_live_transformers_capacity(tmp_path: Path, factory: sessionmaker) -> None:
    """Full path: FRED mock -> refresh_daily -> DB -> recompute -> Score row.

    Asserts:
    - refresh_daily writes >=14 `ppi_transformers` rows
    - recompute_scores produces a `transformers_tnd` score with
      `capacity_tightness` populated and `data_completeness == 1.0`
    """
    settings = _settings_with_fred_key(tmp_path)
    today = date.today()
    # The recompute job's signal-window is `_LOOKBACK_DAYS = 730` from `now`.
    # Anchor `since` 24 months back so the 14 months of FRED data we
    # generate land squarely inside the window. `until` is today.
    until = today
    since = today - timedelta(days=730)

    with respx.mock(base_url=_FRED_BASE_URL) as mock:
        mock.get("/fred/series/observations").mock(side_effect=_fred_response_for_series)
        report = refresh_daily.run(
            settings=settings,
            source_filter=["fred"],
            since=since,
            until=until,
            factory=factory,
        )

    # Sanity: refresh_daily wrote signals.
    assert report.exit_code == 0
    fred_result = next(r for r in report.adapter_results if r["source"] == "fred")
    assert fred_result["status"] == "OK"
    assert fred_result["rows_written"] >= 14

    with factory() as session:
        signals = (
            session.execute(
                select(Signal).where(
                    Signal.signal_name == "ppi_transformers",
                    Signal.segment == "transformers_tnd",
                )
            )
            .scalars()
            .all()
        )
        assert len(signals) >= 14
        assert all(s.source == "fred" for s in signals)
        assert all(s.source_id == "WPU1321" for s in signals)

    # Now run the recompute and assert `transformers_tnd` got a real
    # capacity_tightness (not the seed-only None) and full
    # data_completeness.
    recompute_scores.run(settings=settings, factory=factory)

    with factory() as session:
        rows = session.execute(select(Score)).scalars().all()
        by_segment = {(s.segment, s.horizon): s for s in rows}
        score = by_segment[("transformers_tnd", "near")]
        assert score.sub_scores["capacity_tightness"] is not None
        assert 0.0 <= score.sub_scores["capacity_tightness"] <= 1.0
        # All 5 sub-scores populated → completeness is 1.0.
        assert score.data_completeness == 1.0
        # Score reflects the live data, not the seed.
        assert score.score is not None
