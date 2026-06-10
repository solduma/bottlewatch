"""Shared fixtures for the bottlewatch test suite.

- `engine`  : in-memory sqlite, schema created via Base.metadata.create_all
- `factory` : sessionmaker bound to the engine
- `settings`: a Settings with EIA_API_KEY="test-key" so adapters are
  "configured" but no real network is touched (respx intercepts).
- `tmp_log_path` : a Path the orchestrator can write to without polluting
  the real data/cache/refresh.log.
- `seeded_factory` : a factory with 2 segments of signals + 30
  recomputed scores. Drives the recompute-job and API tests.
- `client` : an httpx.AsyncClient bound to a FastAPI app that
  shares the test `factory`'s engine — so the test can pre-seed
  via `factory` and the app sees the same rows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import init_schema, make_engine, make_session_factory, session_scope
from bottlewatch.app.db.models import Signal
from bottlewatch.app.main import create_app
from bottlewatch.config import Settings
from bottlewatch.jobs import recompute_scores


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = make_engine("sqlite:///:memory:")
    init_schema(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker:
    return make_session_factory(engine)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """A Settings tuned for tests: in-memory DB, a temp refresh log, EIA key set."""
    return Settings(
        app_env="test",
        eia_api_key="test-key",
        fred_api_key="test-key",  # enable FRED for multi-adapter sequence tests
        database_url="sqlite:///:memory:",
        refresh_log_path=tmp_path / "refresh.log",
    )


@pytest.fixture
def settings_no_key(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        eia_api_key=None,
        fred_api_key=None,
        comtrade_api_key=None,
        database_url="sqlite:///:memory:",
        refresh_log_path=tmp_path / "refresh.log",
    )


@pytest.fixture
def tmp_log_path(tmp_path: Path) -> Path:
    return tmp_path / "refresh.log"


def _seed_signals(factory: sessionmaker) -> None:
    """Insert a small fixture set of signals across 2 segments.

    Dates are computed relative to `now` so the recompute job's
    730-day signal window always sees the seeded rows. Hardcoded
    2024/2027 dates drift out of the window as time passes (a
    test that worked in 2024-2025 silently regresses in 2026+).
    """
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    # Anchor "now" at the first of this month so monthly signals
    # land on a stable day boundary and don't shift between
    # morning and evening test runs.
    today = now.date().replace(day=1)
    rows = [
        # power_generation_oem: 2 planned + 1 operating. All
        # within the 730-day window (recent past). The original
        # fixture used 2027 dates that drifted out of the window
        # as time passed — the recompute filters by
        # `observed_at <= now`, so future-dated signals were
        # silently dropped, breaking the test.
        Signal(
            segment="power_generation_oem",
            subsegment=None,
            signal_name="planned_capacity_mw",
            value_num=2000.0,
            unit="MW",
            source="eia_860m",
            source_id="p1",
            observed_at=today - timedelta(days=180),
            ingested_at=now,
        ),
        Signal(
            segment="power_generation_oem",
            subsegment=None,
            signal_name="planned_capacity_mw",
            value_num=3000.0,
            unit="MW",
            source="eia_860m",
            source_id="p2",
            observed_at=today - timedelta(days=90),
            ingested_at=now,
        ),
        Signal(
            segment="power_generation_oem",
            subsegment=None,
            signal_name="capacity_mw",
            value_num=20000.0,
            unit="MW",
            source="eia_v2_capacity",
            source_id="c1",
            observed_at=today - timedelta(days=30),
            ingested_at=now,
        ),
    ]
    # data_center_shell: 24 months of monthly retail_sales_mwh.
    # The _data_center_shell_tightness extractor needs >=13 points
    # for a YoY delta. The first 12 are the "old" period (val 1000),
    # the next 12 are the "new" period (val 1200) — together this
    # gives a +20% YoY growth that lands inside the extractor's
    # [-0.10, +0.25] mapping band.
    # Anchor: latest point is "last month" (the 1st of the month
    # before `today`). 24 months back from there.
    latest_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)  # last month's 1st
    for i in range(24):
        # i=0 → 23 months ago (oldest), i=23 → last month (newest).
        first_of_target = (latest_month - timedelta(days=30 * (23 - i))).replace(day=1)
        val = 1000.0 if i < 12 else 1200.0
        rows.append(
            Signal(
                segment="data_center_shell",
                subsegment=None,
                signal_name="retail_sales_mwh",
                value_num=val,
                unit="MWh",
                source="eia_v2",
                source_id=f"sales{i}",
                observed_at=first_of_target,
                ingested_at=now,
            )
        )
    with session_scope(factory) as session:
        for r in rows:
            session.add(r)


@pytest.fixture
def seeded_factory(settings: Settings, factory: sessionmaker) -> sessionmaker:
    """A factory with 2 segments of signals + 30 recomputed scores."""
    _seed_signals(factory)
    recompute_scores.run(settings=settings, factory=factory)
    return factory


@pytest_asyncio.fixture
async def client(settings: Settings, factory: sessionmaker) -> AsyncIterator[AsyncClient]:
    """An httpx.AsyncClient bound to a FastAPI app that shares
    the test `factory`'s engine. Pre-seed with `seeded_factory`
    (or `_seed_signals(factory)` + `recompute_scores.run(...)`)
    before hitting endpoints.
    """
    app = create_app(settings, session_factory=factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
