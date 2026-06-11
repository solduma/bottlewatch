"""Tests for GET /api/v1/segments + /api/v1/segments/{slug}."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from bottlewatch.jobs import recompute_scores


@pytest.mark.asyncio
async def test_list_returns_30_rows(client: AsyncClient, settings, factory) -> None:
    recompute_scores.run(settings=settings, factory=factory)
    resp = await client.get("/api/v1/segments")
    assert resp.status_code == 200
    body: list[dict[str, Any]] = resp.json()
    assert len(body) == 30  # 10 segments × 3 horizons
    # The set of (segment, horizon) pairs is unique.
    pairs = {(r["segment"], r["horizon"]) for r in body}
    assert len(pairs) == 30


@pytest.mark.asyncio
async def test_list_is_sorted_segment_then_horizon(client: AsyncClient, settings, factory) -> None:
    recompute_scores.run(settings=settings, factory=factory)
    body = (await client.get("/api/v1/segments")).json()
    keys = [(r["segment"], r["horizon"]) for r in body]
    assert keys == sorted(keys)


@pytest.mark.asyncio
async def test_detail_returns_3_horizons_and_recent_signals(client: AsyncClient, seeded_factory) -> None:
    # `seeded_factory` from conftest pre-seeds signals + recomputes.
    resp = await client.get("/api/v1/segments/power_generation_oem")
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    assert body["segment"] == "power_generation_oem"
    assert len(body["horizons"]) == 3
    assert {"near", "med", "long"} == {h["horizon"] for h in body["horizons"]}
    # power_generation_oem has both extractors → completeness 1.0
    assert all(h["data_completeness"] == 1.0 for h in body["horizons"])
    # sub_scores has all 5 sub-scores
    assert set(body["sub_scores"].keys()) == {
        "lead_time_growth",
        "capacity_tightness",
        "geo_concentration",
        "regulatory_friction",
        "demand_signal",
    }
    # The seeded signals come back (3 power + 24 sales = 27 max,
    # or fewer if the limit kicked in).
    assert len(body["signals"]) > 0


@pytest.mark.asyncio
async def test_detail_returns_404_for_unknown(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/segments/does_not_exist")
    assert resp.status_code == 404
    assert "unknown segment" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_research_only_segment_has_no_data_regime(client: AsyncClient, settings, factory) -> None:
    """transformers_tnd has no extractor → completeness 0.8, but
    that's > 0.4 so it gets a real regime (STABLE/PEAKED). The
    NO_DATA label is reserved for < 0.4 completeness.
    """
    recompute_scores.run(settings=settings, factory=factory)
    body = (await client.get("/api/v1/segments/transformers_tnd")).json()
    near = next(h for h in body["horizons"] if h["horizon"] == "near")
    assert near["data_completeness"] == 0.8
    assert near["regime"] != "NO_DATA"


@pytest.mark.asyncio
async def test_list_includes_human_readable_name(client: AsyncClient, settings, factory) -> None:
    """Every row in the segments list must include a `name`
    field that is the human-readable title (not the slug).
    Per docs/plans/2026-06-11-display-names-and-score-help.md
    this is sourced from `app/segments_meta.py`.
    """
    recompute_scores.run(settings=settings, factory=factory)
    body = (await client.get("/api/v1/segments")).json()
    by_slug = {r["segment"]: r for r in body}
    # Spot-check a few known mappings.
    assert by_slug["transformers_tnd"]["name"] == "Transformers & Switchgear (T&D)"
    assert by_slug["hbm_memory"]["name"] == "HBM Memory"
    assert by_slug["systems_rack_scale"]["name"] == "Systems OEM/ODM"


@pytest.mark.asyncio
async def test_detail_includes_human_readable_name(client: AsyncClient, seeded_factory) -> None:
    resp = await client.get("/api/v1/segments/power_generation_oem")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Power Generation OEM"
    # Each horizon row also carries the name.
    for h in body["horizons"]:
        assert h["name"] == "Power Generation OEM"


@pytest.mark.asyncio
async def test_unknown_segment_falls_back_to_slug() -> None:
    """If a slug is passed to display_name() that isn't in the
    meta dict, the function returns the slug itself rather
    than throwing. Tested at the unit level (not via the
    API) because the API returns 404 for unknown segments
    before reaching the display_name() call.
    """
    from bottlewatch.app.segments_meta import display_name

    # Mapped slug → human name.
    assert display_name("transformers_tnd") == "Transformers & Switchgear (T&D)"
    # Unmapped slug → identity fallback.
    assert display_name("not_a_real_segment_xyz") == "not_a_real_segment_xyz"
