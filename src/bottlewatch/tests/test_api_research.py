"""Tests for GET /api/v1/research/daily."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from bottlewatch.app.db import ResearchSnapshot, session_scope


@pytest.mark.asyncio
async def test_get_research_daily_returns_snapshot(client: AsyncClient, seeded_factory) -> None:
    now = datetime.now(tz=timezone.utc)
    with session_scope(seeded_factory) as session:
        session.add(
            ResearchSnapshot(
                segment="advanced_node_fabs",
                horizon="near",
                date=now.date(),
                rationale_md="Test rationale.",
                divergences=[{"sub_score": "lead_time_growth", "seed": 0.85, "dynamic": 0.60, "gap": -0.25}],
                generated_by="llm",
                created_at=now,
            )
        )

    resp = await client.get("/api/v1/research/daily?segment=advanced_node_fabs&horizon=near")
    assert resp.status_code == 200
    body = resp.json()
    assert body["segment"] == "advanced_node_fabs"
    assert body["horizon"] == "near"
    assert body["rationale_md"] == "Test rationale."
    assert body["generated_by"] == "llm"
    assert len(body["divergences"]) == 1
    assert body["divergences"][0]["sub_score"] == "lead_time_growth"


@pytest.mark.asyncio
async def test_get_research_daily_defaults_to_today(client: AsyncClient, seeded_factory) -> None:
    now = datetime.now(tz=timezone.utc)
    with session_scope(seeded_factory) as session:
        session.add(
            ResearchSnapshot(
                segment="advanced_node_fabs",
                horizon="all",
                date=now.date(),
                rationale_md="All-horizon summary.",
                divergences=[],
                generated_by="machine",
                created_at=now,
            )
        )

    resp = await client.get("/api/v1/research/daily?segment=advanced_node_fabs")
    assert resp.status_code == 200
    assert resp.json()["horizon"] == "all"


@pytest.mark.asyncio
async def test_get_research_daily_404_for_missing_snapshot(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/research/daily?segment=not_a_segment&horizon=near")
    assert resp.status_code == 404
    assert "not_a_segment" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_research_daily_rejects_bad_horizon(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/research/daily?segment=advanced_node_fabs&horizon=weekly")
    assert resp.status_code == 400
