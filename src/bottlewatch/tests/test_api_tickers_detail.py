"""Tests for GET /api/v1/tickers/{ticker}."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_ticker_detail_returns_ticker_info(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/tickers/TSM")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "TSM"
    assert body["exchange"] == "NYSE"
    assert body["name"] == "TSMC"


@pytest.mark.asyncio
async def test_ticker_detail_includes_segments(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/tickers/TSM")
    assert resp.status_code == 200
    body = resp.json()
    assert "segments" in body
    assert len(body["segments"]) >= 1
    tsm_seg = next(s for s in body["segments"] if s["segment"] == "advanced_node_fabs")
    assert tsm_seg["subsegment"] == "foundry_lead_node"
    assert tsm_seg["exposure_pct"] == 90.0


@pytest.mark.asyncio
async def test_ticker_detail_includes_optional_fields(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/tickers/TSM")
    assert resp.status_code == 200
    body = resp.json()
    assert "thesis" in body
    assert "companies" in body  # from the value chain node


@pytest.mark.asyncio
async def test_ticker_detail_not_found(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/tickers/NOTATICKER")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ticker_detail_has_segments_with_regime_fields(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/tickers/TSM")
    assert resp.status_code == 200
    seg = next(s for s in resp.json()["segments"] if s["segment"] == "advanced_node_fabs")
    required = {"segment", "subsegment", "exposure_pct", "regime_near", "score_near", "momentum_near"}
    assert required.issubset(seg.keys())
    # Score/rego fields come from the scores table — seeded_factory runs recompute.
    assert seg["regime_near"] is not None


@pytest.mark.asyncio
async def test_ticker_detail_ticker_with_no_segments(client: AsyncClient, seeded_factory) -> None:
    # A ticker in the universe CSV but with no matching segment in scores.
    # TSM is in both; use a known ticker.
    resp = await client.get("/api/v1/tickers/NVDA")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "NVDA"
    # Should have at least gpu_asic_silicon segment.
    assert len(body["segments"]) >= 1


@pytest.mark.asyncio
async def test_ticker_detail_companies_for_slug_mismatch_segment(client: AsyncClient, seeded_factory) -> None:
    """Regression test for the value-chain slug mismatch.

    HUBB's CSV segment is `transformers_tnd`; the value-chain JSON
    node id is `transformers_switchgear`. The shared translation in
    `app.value_chain.SEGMENT_TO_NODE_ID` bridges the two. Before
    the fix, `companies` was silently empty for this and the
    `systems_rack_scale` ↔ `rack_scale_integration` pair.
    """
    resp = await client.get("/api/v1/tickers/HUBB")
    assert resp.status_code == 200
    body = resp.json()
    # transformers_switchgear (value chain) has Hubbell in its companies list.
    assert "HUBB" in body["companies"]
    assert len(body["companies"]) > 1


@pytest.mark.asyncio
async def test_ticker_detail_companies_for_systems_rack_scale(client: AsyncClient, seeded_factory) -> None:
    """Regression test for the `systems_rack_scale` ↔ `rack_scale_integration` mismatch."""
    resp = await client.get("/api/v1/tickers/SMCI")
    assert resp.status_code == 200
    body = resp.json()
    # rack_scale_integration (value chain) has SMCI in its companies list.
    assert "SMCI" in body["companies"]
    assert len(body["companies"]) > 1
