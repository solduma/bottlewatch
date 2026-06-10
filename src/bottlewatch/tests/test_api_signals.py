"""Tests for GET /api/v1/signals?segment=...&limit=50."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_filtered_by_segment(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/signals?segment=power_generation_oem&limit=100")
    assert resp.status_code == 200
    body: list[dict[str, Any]] = resp.json()
    assert all(r["segment"] == "power_generation_oem" for r in body)
    # The seeded set is 3 power signals.
    assert len(body) == 3


@pytest.mark.asyncio
async def test_unknown_segment_returns_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/signals?segment=does_not_exist")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_default_limit_applies(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/signals")
    assert resp.status_code == 200
    body = resp.json()
    # Default limit is 50; seeded set is 27 → all returned.
    assert len(body) == 27


@pytest.mark.asyncio
async def test_limit_capped_at_500(client: AsyncClient) -> None:
    # 1000 is over the cap; FastAPI returns 422 on the validation.
    resp = await client.get("/api/v1/signals?limit=1000")
    assert resp.status_code == 422
