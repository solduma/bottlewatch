"""Tests for the ?horizon= query param on /api/v1/segments."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from bottlewatch.jobs import recompute_scores


@pytest.mark.asyncio
async def test_horizon_filter_near_returns_64_rows(client: AsyncClient, settings, factory) -> None:
    recompute_scores.run(settings=settings, factory=factory)
    resp = await client.get("/api/v1/segments?horizon=near")
    assert resp.status_code == 200
    body: list[dict[str, Any]] = resp.json()
    assert len(body) == 64
    assert all(r["horizon"] == "near" for r in body)


@pytest.mark.asyncio
async def test_horizon_filter_med_returns_64_rows(client: AsyncClient, settings, factory) -> None:
    recompute_scores.run(settings=settings, factory=factory)
    resp = await client.get("/api/v1/segments?horizon=med")
    assert resp.status_code == 200
    body: list[dict[str, Any]] = resp.json()
    assert len(body) == 64
    assert all(r["horizon"] == "med" for r in body)


@pytest.mark.asyncio
async def test_horizon_filter_long_returns_64_rows(client: AsyncClient, settings, factory) -> None:
    recompute_scores.run(settings=settings, factory=factory)
    resp = await client.get("/api/v1/segments?horizon=long")
    assert resp.status_code == 200
    body: list[dict[str, Any]] = resp.json()
    assert len(body) == 64
    assert all(r["horizon"] == "long" for r in body)


@pytest.mark.asyncio
async def test_horizon_filter_bogus_returns_400(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/segments?horizon=bogus")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_horizon_filter_omitted_returns_192(client: AsyncClient, settings, factory) -> None:
    """Backwards compat: no ?horizon= param still returns all 192 rows."""
    recompute_scores.run(settings=settings, factory=factory)
    resp = await client.get("/api/v1/segments")
    assert resp.status_code == 200
    body: list[dict[str, Any]] = resp.json()
    assert len(body) == 192
