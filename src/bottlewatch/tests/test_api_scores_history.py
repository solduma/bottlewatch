"""Tests for GET /api/v1/scores/history."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_scores_history_empty_on_first_run(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/scores/history?segment=advanced_packaging&horizon=near")
    assert resp.status_code == 200
    body = resp.json()
    assert body["segment"] == "advanced_packaging"
    assert body["horizon"] == "near"
    # seeded_factory runs recompute, which writes the score_history row,
    # so we always have at least the current point.
    assert len(body["points"]) >= 1


@pytest.mark.asyncio
async def test_scores_history_requires_segment(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/scores/history")
    assert resp.status_code == 422  # segment is required


@pytest.mark.asyncio
async def test_scores_history_requires_horizon(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/scores/history?segment=advanced_packaging")
    assert resp.status_code == 422  # horizon is required


@pytest.mark.asyncio
async def test_scores_history_unknown_segment(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/scores/history?segment=unknown_segment&horizon=near")
    assert resp.status_code == 200
    body = resp.json()
    assert body["segment"] == "unknown_segment"
    assert body["points"] == []


@pytest.mark.asyncio
async def test_scores_history_unknown_horizon(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/scores/history?segment=advanced_packaging&horizon=bogus")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_scores_history_response_shape(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/scores/history?segment=advanced_packaging&horizon=med")
    assert resp.status_code == 200
    body = resp.json()
    required = {"segment", "horizon", "points"}
    assert required.issubset(body.keys())
    for p in body["points"]:
        assert {"computed_at", "b", "momentum", "regime"} <= set(p.keys())


# ---------------------------------------------------------------------------
# Batched endpoint (?segments=a,b,c) — used by the scoreboard to fetch
# all sparkline series in a single round-trip. Replaces the per-row
# N+1 calls from ScoreboardTable.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scores_history_batched_returns_one_entry_per_requested_segment(
    client: AsyncClient, seeded_factory
) -> None:
    """Batched response includes one `series` entry per requested
    segment, in the request order, with `points: []` for segments
    that have no history.
    """
    resp = await client.get(
        "/api/v1/scores/history?segments=power_generation_oem,unknown_segment,data_center_shell&horizon=near"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["horizon"] == "near"
    # series is the new top-level key; segment is not (the batched
    # response carries the list).
    assert body["series"] == [
        {"segment": "power_generation_oem", "points": body["series"][0]["points"]},
        {"segment": "unknown_segment", "points": []},
        {"segment": "data_center_shell", "points": body["series"][2]["points"]},
    ]
    # Seeded segments have at least 1 point (recompute writes it).
    assert len(body["series"][0]["points"]) >= 1
    assert len(body["series"][2]["points"]) >= 1
    # The empty one is a stub shape only.
    assert body["series"][1]["points"] == []


@pytest.mark.asyncio
async def test_scores_history_batched_and_single_are_mutually_exclusive(client: AsyncClient, seeded_factory) -> None:
    """Both `segment` and `segments` provided → 400."""
    resp = await client.get(
        "/api/v1/scores/history?segment=power_generation_oem&segments=power_generation_oem&horizon=near"
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_scores_history_batched_empty_segments_400(client: AsyncClient, seeded_factory) -> None:
    """`segments=` (empty value) → 400. The scoreboard sends
    comma-separated slugs; an empty list is a programmer error.
    """
    resp = await client.get("/api/v1/scores/history?segments=&horizon=near")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_scores_history_batched_unknown_segment_returns_empty(client: AsyncClient, seeded_factory) -> None:
    """An unknown slug in the batched request is not an error; it
    appears in `series` with `points: []`. The scoreboard treats
    this as a stale or soon-to-be-added segment.
    """
    resp = await client.get("/api/v1/scores/history?segments=does_not_exist&horizon=near")
    assert resp.status_code == 200
    body = resp.json()
    assert body["series"] == [{"segment": "does_not_exist", "points": []}]


@pytest.mark.asyncio
async def test_scores_history_single_segment_still_works(client: AsyncClient, seeded_factory) -> None:
    """Backward-compat: the single-`segment` path is unchanged
    (the ticker detail page still uses it).
    """
    resp = await client.get("/api/v1/scores/history?segment=power_generation_oem&horizon=near")
    assert resp.status_code == 200
    body = resp.json()
    assert body["segment"] == "power_generation_oem"
    assert body["horizon"] == "near"
    assert "points" in body
    assert "series" not in body  # single response is the old shape


@pytest.mark.asyncio
async def test_scores_history_batched_requires_horizon(client: AsyncClient, seeded_factory) -> None:
    """`horizon` is required for the batched endpoint too."""
    resp = await client.get("/api/v1/scores/history?segments=power_generation_oem")
    assert resp.status_code == 422  # FastAPI's required-param check


@pytest.mark.asyncio
async def test_scores_history_batched_unknown_horizon(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/scores/history?segments=power_generation_oem&horizon=bogus")
    assert resp.status_code == 400
