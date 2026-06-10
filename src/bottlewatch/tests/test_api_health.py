"""Tests for GET /api/v1/health."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from bottlewatch.jobs import recompute_scores


@pytest.mark.asyncio
async def test_health_returns_db_ok_and_counts(client: AsyncClient, settings, factory) -> None:
    recompute_scores.run(settings=settings, factory=factory)
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["db_ok"] is True
    assert body["signals_count"] == 0  # the `factory` has no seeded signals
    assert body["last_score_at"] is not None


@pytest.mark.asyncio
async def test_health_handles_empty_db(client: AsyncClient) -> None:
    # No signals, no scores — health should still 200 with nulls.
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db_ok"] is True
    assert body["last_score_at"] is None
    assert body["signals_count"] == 0
