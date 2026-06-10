"""Tests for GET /api/v1/map/{slug}."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_map_node_returns_node_info(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/map/advanced_packaging")
    assert resp.status_code == 200
    body = resp.json()
    assert body["node"]["id"] == "advanced_packaging"
    assert body["node"]["label"] == "advanced packaging"


@pytest.mark.asyncio
async def test_map_node_includes_regime_fields(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/map/advanced_packaging")
    assert resp.status_code == 200
    node = resp.json()["node"]
    required = {"id", "label", "sector", "regime", "score", "momentum"}
    assert required.issubset(node.keys())


@pytest.mark.asyncio
async def test_map_node_includes_upstream_and_downstream(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/map/advanced_packaging")
    assert resp.status_code == 200
    body = resp.json()
    assert "upstream" in body
    assert "downstream" in body
    assert isinstance(body["upstream"], list)
    assert isinstance(body["downstream"], list)


@pytest.mark.asyncio
async def test_map_node_includes_companies_eta_thesis(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/map/advanced_packaging")
    assert resp.status_code == 200
    body = resp.json()
    assert "companies" in body
    assert "eta" in body
    assert "thesis_count" in body


@pytest.mark.asyncio
async def test_map_node_not_found(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/map/not_a_real_node")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_map_node_upstream_has_depth(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/map/advanced_packaging")
    assert resp.status_code == 200
    for node in resp.json()["upstream"]:
        assert "id" in node
        assert "regime" in node
        assert "depth" in node
        assert node["depth"] >= 1


@pytest.mark.asyncio
async def test_map_node_downstream_has_depth(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/map/advanced_packaging")
    assert resp.status_code == 200
    for node in resp.json()["downstream"]:
        assert "id" in node
        assert "regime" in node
        assert "depth" in node
        assert node["depth"] >= 1
