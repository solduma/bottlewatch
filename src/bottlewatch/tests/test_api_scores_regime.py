"""Tests for GET /api/v1/scores/regime."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from bottlewatch.jobs import recompute_scores


@pytest.mark.asyncio
async def test_regime_returns_30_rows_with_required_fields(client: AsyncClient, settings, factory) -> None:
    recompute_scores.run(settings=settings, factory=factory)
    resp = await client.get("/api/v1/scores/regime")
    assert resp.status_code == 200
    body: list[dict[str, Any]] = resp.json()
    assert len(body) == 30  # 10 segments × 3 horizons

    # Every row has the fields the quadrant needs.
    required = {
        "segment",
        "horizon",
        "score",
        "momentum",
        "regime",
        "regime_confidence",
        "data_completeness",
        "computed_at",
    }
    for row in body:
        assert required.issubset(row.keys())


@pytest.mark.asyncio
async def test_regime_includes_horizon_filter(client: AsyncClient, settings, factory) -> None:
    recompute_scores.run(settings=settings, factory=factory)
    resp = await client.get("/api/v1/scores/regime?horizon=near")
    assert resp.status_code == 200
    body: list[dict[str, Any]] = resp.json()
    assert len(body) == 10
    assert all(r["horizon"] == "near" for r in body)


@pytest.mark.asyncio
async def test_regime_values_are_in_expected_ranges(client: AsyncClient, settings, factory) -> None:
    recompute_scores.run(settings=settings, factory=factory)
    body = (await client.get("/api/v1/scores/regime")).json()
    for row in body:
        # score is None or 0-100
        if row["score"] is not None:
            assert 0.0 <= row["score"] <= 100.0
        # regime is one of the known labels
        assert row["regime"] in {
            "PEAKING",
            "PEAKED",
            "RESOLVING",
            "EMERGING",
            "STABLE",
            "RESOLVING_FROM_LOW",
            "NO_DATA",
        }
        # confidence is low/medium/high
        assert row["regime_confidence"] in {"low", "medium", "high"}
