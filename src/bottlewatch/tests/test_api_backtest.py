"""Tests for GET /api/v1/backtest/report."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import ScoreHistory, session_scope


def _seed_score_history(factory: sessionmaker) -> None:
    """Seed a short score_history trail for two universe segments."""
    base = datetime(2024, 6, 1, tzinfo=timezone.utc).replace(tzinfo=None)
    rows = []
    for i in range(6):
        ts = base + timedelta(days=30 * i)
        for seg, b in (("advanced_node_fabs", 0.8), ("gpu_asic_silicon", 0.6)):
            rows.append(
                ScoreHistory(
                    segment=seg,
                    horizon="near",
                    computed_at=ts,
                    b=b,
                    momentum=0.0,
                    regime="STABLE",
                )
            )
    with session_scope(factory) as session:
        for r in rows:
            session.add(r)


@pytest.mark.asyncio
async def test_backtest_report_returns_valid_shape(client: AsyncClient, factory: sessionmaker) -> None:
    """The endpoint returns a JSON report with the expected top-level keys."""
    _seed_score_history(factory)

    resp = await client.get("/api/v1/backtest/report?start=2024-09-01&end=2024-12-01&horizon=near&forward_days=60")
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["horizon"] == "near"
    assert body["forward_days"] == 60
    assert "overall_ic" in body
    assert "per_segment_ic" in body
    assert "baskets" in body
    assert "fixed_vs_rolling" in body
    assert len(body["baskets"]) > 0
    first = body["baskets"][0]
    for key in (
        "weights",
        "equal_weight_return",
        "net_return",
        "volatility",
        "max_drawdown",
        "hit_rate",
        "coverage",
        "sector_neutral",
    ):
        assert key in first


@pytest.mark.asyncio
async def test_backtest_report_validates_horizon(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/backtest/report?horizon=invalid")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_backtest_report_validates_dates(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/backtest/report?start=2025-01-01&end=2024-01-01")
    assert resp.status_code == 400
