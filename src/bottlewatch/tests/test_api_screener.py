"""Tests for GET /api/v1/screener.

Verifies the hard guard from plan §7.4:
  /screener?side=long  → must EXCLUDE segments in RESOLVING regime
  /screener?side=short → must RETURN only segments in RESOLVING regime,
                          sorted by B × |B'| descending

Both endpoints are segment-level (one row per segment × horizon).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from bottlewatch.app.db.models import Score
from bottlewatch.app.score.regime import Regime
from bottlewatch.jobs import recompute_scores
from bottlewatch.app.db import session_scope


def _seed_resolving_segment(
    factory,
    *,
    segment: str,
    horizon: str,
    score: float,
    momentum: float,
) -> None:
    """Insert one (segment, horizon) score row with a specific B and B'.

    Used to verify the hard guard works on a segment that is actually
    in the RESOLVING regime. The default test fixture has all momentum=0,
    so no segment is in RESOLVING without this seed.
    """
    from datetime import datetime, timezone

    with session_scope(factory) as session:
        existing = session.get(Score, (segment, horizon))
        if existing is not None:
            existing.score = score
            existing.momentum = momentum
            existing.regime = Regime.RESOLVING.value
        else:
            now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
            session.add(
                Score(
                    segment=segment,
                    horizon=horizon,
                    score=score,
                    momentum=momentum,
                    regime=Regime.RESOLVING.value,
                    regime_confidence="high",
                    sub_scores={},
                    data_completeness=1.0,
                    first_computed_at=now,
                    computed_at=now,
                )
            )


@pytest.mark.asyncio
async def test_screener_long_excludes_resolving(client: AsyncClient, settings, factory) -> None:
    """Seed a segment in RESOLVING regime; long basket must exclude it."""
    _seed_resolving_segment(factory, segment="power_generation_oem", horizon="near", score=85.0, momentum=-30.0)
    recompute_scores.run(settings=settings, factory=factory)  # rebuilds the other 29 rows
    # Re-seed after recompute (recompute wipes the table).
    _seed_resolving_segment(factory, segment="power_generation_oem", horizon="near", score=85.0, momentum=-30.0)

    resp = await client.get("/api/v1/screener?side=long&horizon=near")
    assert resp.status_code == 200
    body: list[dict[str, Any]] = resp.json()

    # The resolving segment must not appear in the long basket.
    assert not any(r["segment"] == "power_generation_oem" for r in body)
    # The other segments with non-RESOLVING regimes are eligible.
    for r in body:
        assert r["regime"] != "RESOLVING"


@pytest.mark.asyncio
async def test_screener_short_returns_only_resolving(client: AsyncClient, settings, factory) -> None:
    _seed_resolving_segment(factory, segment="advanced_packaging", horizon="near", score=78.0, momentum=-13.0)
    recompute_scores.run(settings=settings, factory=factory)
    _seed_resolving_segment(factory, segment="advanced_packaging", horizon="near", score=78.0, momentum=-13.0)

    resp = await client.get("/api/v1/screener?side=short&horizon=near")
    assert resp.status_code == 200
    body: list[dict[str, Any]] = resp.json()

    for r in body:
        assert r["regime"] == "RESOLVING"

    # Sorted by B × |B'| descending.
    keys = [r["score"] * abs(r["momentum"]) for r in body]
    assert keys == sorted(keys, reverse=True)


@pytest.mark.asyncio
async def test_screener_unknown_side_returns_400(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/screener?side=bogus&horizon=near")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_screener_invalid_horizon_returns_400(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/screener?side=long&horizon=bogus")
    assert resp.status_code == 400
