"""End-to-end user-journey test for the M2 surface.

Walks the full pipeline: mocked network ingest → orchestrator →
recompute → FastAPI endpoints → response shape. This is the
capstone regression test: a single failure here means the
dashboard's load-bearing user path is broken, regardless of how
many unit tests pass.

Steps:
1. Mocks the EIA v2 + FRED network with realistic payloads.
2. Runs `refresh_daily.run(source_filter=["eia_v2", "fred"])`
   against an in-memory DB.
3. Runs `recompute_scores.run()`.
4. Asserts the FastAPI endpoints return what the dashboard needs:
   - `/api/v1/health` says db_ok=True
   - `/api/v1/segments` returns 10 scoring segments
   - `/api/v1/scores/regime` returns rows with regimes
   - `/api/v1/map` returns nodes + edges
   - `/api/v1/tickers/HUBB` returns non-empty `companies` (catches
     the value-chain slug-mismatch bug — HUBB is in the
     `transformers_tnd` segment which has a non-trivial slug mapping)
   - The signals table has zero rows from stub sources
     (sec_edgar, sec_insider, epa_egrid)
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import Signal
from bottlewatch.app.ingest.eia import _SERIES_SPEC
from bottlewatch.config import Settings
from bottlewatch.jobs import recompute_scores, refresh_daily

_BASE_URL = "https://api.eia.gov/v2"
_FRED_BASE_URL = "https://api.stlouisfed.org"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        eia_api_key="test-key",
        fred_api_key="test-key",
        database_url="sqlite:///:memory:",
        refresh_log_path=tmp_path / "refresh.log",
    )


def _eia_envelope(data: list[dict[str, Any]]) -> dict[str, Any]:
    return {"response": {"total": len(data), "data": data}}


def _fred_response_for_series(request: httpx.Request) -> httpx.Response:
    """Return 14 months of monthly FRED data with growing values
    for the transformers PPI series; empty observations for the
    other 3 FRED series."""
    sid = request.url.params.get("series_id")
    if sid != "WPU1321":
        return httpx.Response(200, json={"observations": []})
    today = date.today()
    observations: list[dict[str, str]] = []
    value = 100.0
    for months_ago in range(13, -1, -1):
        d = today - timedelta(days=30 * months_ago)
        observations.append({"date": d.isoformat(), "value": f"{value:.2f}"})
        value *= 1.03
    return httpx.Response(200, json={"observations": observations})


_STUB_SOURCES = ("sec_edgar", "sec_insider", "epa_egrid")


@pytest.mark.asyncio
async def test_full_user_journey(tmp_path: Path, factory: sessionmaker, client: AsyncClient) -> None:
    """One test, full pipeline. If this passes, the dashboard can
    render the scoreboard, drill into a segment, and surface a
    ticker's companies list."""
    settings = _settings(tmp_path)
    today = date.today()
    since = today - timedelta(days=730)
    until = today

    with (
        respx.mock(base_url=_BASE_URL, assert_all_called=False) as eia_mock,
        respx.mock(base_url=_FRED_BASE_URL, assert_all_called=False) as fred_mock,
    ):
        # EIA: every series returns a small 2-point response.
        for s in _SERIES_SPEC:
            payload = (
                [{"period": f"2024-{m:02d}", "sales": 2500 + m} for m in range(1, 3)]
                if s["series_id"].endswith(".M")
                else [{"period": 2024, "generation": 4000}]
            )
            eia_mock.get(f"/seriesid/{s['series_id']}").respond(200, json=_eia_envelope(payload))
        # FRED: 14 months of WPU1321, empty for others.
        fred_mock.get("/fred/series/observations").mock(side_effect=_fred_response_for_series)
        refresh_report = refresh_daily.run(
            settings=settings,
            source_filter=["eia_v2", "fred"],
            since=since,
            until=until,
            dry_run=False,
            factory=factory,
        )

    # Refresh produced rows for both sources.
    by_source = {r["source"]: r for r in refresh_report.adapter_results}
    assert by_source["eia_v2"]["status"] == "OK", by_source
    assert by_source["fred"]["status"] == "OK", by_source

    # No stub-source signals ended up in the DB.
    with factory() as session:
        stub_rows = session.execute(select(Signal).where(Signal.source.in_(_STUB_SOURCES))).scalars().all()
        assert stub_rows == [], f"stub sources wrote {len(stub_rows)} rows"

    # Recompute populates the scores table.
    recompute_report = recompute_scores.run(settings=settings, factory=factory)
    assert recompute_report.exit_code == 0
    assert recompute_report.rows_written == 192  # 64 segments × 3 horizons

    # FastAPI endpoints: health → segments → scores → map → ticker.
    health = (await client.get("/api/v1/health")).json()
    assert health["db_ok"] is True
    assert health["signals_count"] > 0

    segs = (await client.get("/api/v1/segments")).json()
    # /api/v1/segments returns 192 rows (64 segments × 3 horizons)
    assert len(segs) == 192
    segments_seen = {s["segment"] for s in segs}
    assert len(segments_seen) == 64

    scores = (await client.get("/api/v1/scores/regime?horizon=near")).json()
    assert len(scores) == 64
    for row in scores:
        assert row["regime"] in {
            "PEAKING",
            "PEAKED",
            "RESOLVING",
            "EMERGING",
            "STABLE",
            "RESOLVING_FROM_LOW",
            "NO_DATA",
        }

    chain = (await client.get("/api/v1/map")).json()
    assert len(chain["nodes"]) > 0
    assert len(chain["edges"]) > 0

    # HUBB is in `transformers_tnd` whose value-chain node id
    # differs from the segment slug (`transformers_switchgear`).
    # The shared `SEGMENT_TO_NODE_ID` translation is what makes
    # `companies` non-empty for this ticker.
    hubb = (await client.get("/api/v1/tickers/HUBB")).json()
    assert "HUBB" in hubb["companies"], hubb
    assert len(hubb["companies"]) > 1

    # transformers_tnd has no live capacity_tightness extractor, so that
    # sub-score is imputed; on the near horizon its weight is 0.35, so
    # completeness is 1 - 0.35 = 0.65 (the four research sub-scores are
    # seed-backed and count as complete). This reflects the imputation
    # honestly rather than the old constant-1.0 bug.
    transformers = next(r for r in scores if r["segment"] == "transformers_tnd")
    assert transformers["data_completeness"] == pytest.approx(0.65)
