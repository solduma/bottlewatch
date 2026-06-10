"""GET /api/v1/eta.

Resolution ETA stub per plan §7.3. For M2, this is a static
directional estimate per segment read from a small in-file table.
The real implementation will compute from announced capacity
additions + permitting timelines (M3 work).

The 3 ETA bands per the plan:
- <12mo   : bottleneck likely to ease within a year
- 12-24mo : medium-term relief
- >24mo   : structural / long-horizon

Format: {"etas": [{"segment": "...", "eta": "<12mo|12-24mo|>24mo", "confidence": "low|medium|high"}]}

M2 debt: `contributing_capacity` (the 3-5 named capacity additions
per segment driving the ETA estimate) is pending. The plan §7.7
calls for a manual ledger in `research/06_capacity_ledger.md` and
automation in v2.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from bottlewatch.app.config_loader import load_eta_table


router = APIRouter(tags=["eta"])


# Static ETA table for M2. These mirror the per-segment notes in
# research/02_universe.csv and the per-segment regime calls in
# 04_scoring_methodology.md. v1.1 derives this from announced
# capacity + permitting timelines.
# The table lives in research/config/eta.json so it can be edited
# without a code change; this view is a frozen read for import-time
# access.
_STATIC_ETA: dict[str, tuple[str, str]] = {
    seg: (info["eta"], info["confidence"]) for seg, info in load_eta_table().items()
}

VALID_HORIZONS = ("near", "med", "long")


class EtaEntry(BaseModel):
    segment: str
    eta: str
    confidence: str
    # horizon is None (excluded from JSON) for the global view, or
    # set to "near"|"med"|"long" when the caller filtered to one.
    horizon: str | None = None


@router.get("/eta", response_model=dict)
def get_eta(
    horizon: str | None = Query(
        default=None,
        description="Filter to one horizon. Omit for the global estimate.",
    ),
) -> dict:
    if horizon is not None and horizon not in VALID_HORIZONS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown horizon: {horizon!r}; expected one of {list(VALID_HORIZONS)}",
        )
    # The M2 stub doesn't vary by horizon; the segment is the key.
    # horizon=None is excluded from the JSON response (model_dump
    # uses exclude_none=True) for the global view. When filtered,
    # each entry carries the horizon for forward-compat with M3's
    # per-horizon ETA model.
    entries = [
        EtaEntry(
            segment=seg,
            eta=eta,
            confidence=conf,
            horizon=horizon,
        )
        for seg, (eta, conf) in _STATIC_ETA.items()
    ]
    return {"etas": [e.model_dump(exclude_none=True) for e in entries]}
