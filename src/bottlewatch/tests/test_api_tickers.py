"""Tests for GET /api/v1/tickers."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from bottlewatch.jobs import recompute_scores


@pytest.mark.asyncio
async def test_tickers_returns_rows(client: AsyncClient, settings, factory) -> None:
    recompute_scores.run(settings=settings, factory=factory)
    resp = await client.get("/api/v1/tickers")
    assert resp.status_code == 200
    body: list[dict[str, Any]] = resp.json()
    assert len(body) > 0  # the universe has 131 tickers per the M0 research


@pytest.mark.asyncio
async def test_ticker_row_has_required_fields(client: AsyncClient, settings, factory) -> None:
    recompute_scores.run(settings=settings, factory=factory)
    body = (await client.get("/api/v1/tickers")).json()
    required = {"ticker", "name", "segment", "exposure_pct"}
    for row in body:
        assert required.issubset(row.keys())


@pytest.mark.asyncio
async def test_tickers_filter_by_segment(client: AsyncClient, settings, factory) -> None:
    """?segment= query param filters the universe to one segment."""
    recompute_scores.run(settings=settings, factory=factory)
    resp = await client.get("/api/v1/tickers?segment=power_generation_oem")
    assert resp.status_code == 200
    body: list[dict[str, Any]] = resp.json()
    assert all(r["segment"] == "power_generation_oem" for r in body)
