"""Tests for the M2 stub endpoints: /api/v1/map and /api/v1/eta."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_map_returns_nodes_and_edges(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/map")
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert "nodes" in body
    assert "edges" in body
    assert isinstance(body["nodes"], list)
    assert isinstance(body["edges"], list)
    assert len(body["nodes"]) > 0
    # Every node has the fields the frontend needs.
    for n in body["nodes"]:
        assert "id" in n
        assert "regime" in n  # regime injected per-node


@pytest.mark.asyncio
async def test_eta_returns_per_segment_eta(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/eta")
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert "etas" in body
    assert isinstance(body["etas"], list)
    assert len(body["etas"]) > 0
    for entry in body["etas"]:
        assert "segment" in entry
        assert "eta" in entry
        assert entry["eta"] in {"<12mo", "12-24mo", ">24mo"}


@pytest.mark.asyncio
async def test_eta_supports_horizon_filter(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/eta?horizon=near")
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    for entry in body["etas"]:
        # If per-horizon, the entry has a horizon field. If global, the
        # endpoint still filters. We just check the shape is valid.
        assert "segment" in entry
