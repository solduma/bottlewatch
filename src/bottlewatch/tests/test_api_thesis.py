"""Tests for GET/POST/DELETE /api/v1/thesis."""

from __future__ import annotations


import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_post_thesis_creates_row(client: AsyncClient, seeded_factory) -> None:
    resp = await client.post(
        "/api/v1/thesis",
        json={
            "segment": "advanced_packaging",
            "ticker": None,
            "side": "long",
            "body_md": "I disagree with the RESOLVING call — AP7 ramp is delayed.",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["segment"] == "advanced_packaging"
    assert body["ticker"] is None
    assert body["side"] == "long"
    assert body["body_md"] == "I disagree with the RESOLVING call — AP7 ramp is delayed."
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


@pytest.mark.asyncio
async def test_post_thesis_with_ticker(client: AsyncClient, seeded_factory) -> None:
    resp = await client.post(
        "/api/v1/thesis",
        json={
            "segment": "gpu_asic_silicon",
            "ticker": "NVDA",
            "side": "short",
            "body_md": "Not shorting — Blackwell supply still constrained.",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["ticker"] == "NVDA"
    assert body["side"] == "short"


@pytest.mark.asyncio
async def test_post_thesis_validates_body_md(client: AsyncClient, seeded_factory) -> None:
    resp = await client.post(
        "/api/v1/thesis",
        json={"segment": "advanced_packaging", "body_md": ""},
    )
    assert resp.status_code == 422  # body_md is required non-empty


@pytest.mark.asyncio
async def test_post_thesis_validates_segment_required(client: AsyncClient, seeded_factory) -> None:
    resp = await client.post(
        "/api/v1/thesis",
        json={"body_md": "Some text", "segment": ""},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_thesis_empty(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/thesis")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_thesis_with_notes(client: AsyncClient, seeded_factory) -> None:
    # Create two notes.
    await client.post(
        "/api/v1/thesis",
        json={"segment": "advanced_packaging", "side": "long", "body_md": "Note one"},
    )
    await client.post(
        "/api/v1/thesis",
        json={"segment": "advanced_packaging", "side": "long", "body_md": "Note two"},
    )
    resp = await client.get("/api/v1/thesis?segment=advanced_packaging")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    # Newest first.
    assert body[0]["body_md"] == "Note two"
    assert body[1]["body_md"] == "Note one"


@pytest.mark.asyncio
async def test_get_thesis_filter_by_ticker(client: AsyncClient, seeded_factory) -> None:
    await client.post(
        "/api/v1/thesis",
        json={"segment": "gpu_asic_silicon", "ticker": "NVDA", "body_md": "NVDA note"},
    )
    await client.post(
        "/api/v1/thesis",
        json={"segment": "gpu_asic_silicon", "ticker": "AMD", "body_md": "AMD note"},
    )
    resp = await client.get("/api/v1/thesis?ticker=NVDA")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["ticker"] == "NVDA"


@pytest.mark.asyncio
async def test_delete_thesis(client: AsyncClient, seeded_factory) -> None:
    # Create.
    created = (
        await client.post(
            "/api/v1/thesis",
            json={"segment": "advanced_packaging", "body_md": "To be deleted"},
        )
    ).json()
    thesis_id = created["id"]

    # Delete.
    resp = await client.delete(f"/api/v1/thesis/{thesis_id}")
    assert resp.status_code == 204

    # Confirm gone.
    all_theses = (await client.get("/api/v1/thesis")).json()
    assert all(t["id"] != thesis_id for t in all_theses)


@pytest.mark.asyncio
async def test_delete_thesis_not_found(client: AsyncClient, seeded_factory) -> None:
    resp = await client.delete("/api/v1/thesis/99999")
    assert resp.status_code == 404
