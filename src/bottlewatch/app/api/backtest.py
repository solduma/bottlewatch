"""GET /api/v1/backtest/report.

Returns the walk-forward backtest report for the requested window.
The endpoint is read-only but potentially slow (it scans score_history
and prices), so callers should not block the UI on it.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from bottlewatch.app.backtest.prices import CsvPriceProvider
from bottlewatch.jobs.backtest import _DEFAULT_PRICES, run_backtest

router = APIRouter(tags=["backtest"])


def _default_dates() -> tuple[date, date]:
    """Default to the last 180 days of history."""
    end = date.today()
    start = end - timedelta(days=180)
    return start, end


@router.get("/backtest/report", response_model=dict[str, Any])
def get_backtest_report(
    request: Request,
    start: date | None = Query(default=None, description="First evaluation date (YYYY-MM-DD)."),
    end: date | None = Query(default=None, description="Last evaluation date (YYYY-MM-DD)."),
    horizon: str = Query(default="near", description="Score horizon: near | med | long."),
    forward_days: int = Query(default=90, ge=1, description="Forward return window in calendar days."),
    normalization_mode: str = Query(default="fixed", description="Primary mode: fixed | rolling | both."),
) -> dict[str, Any]:
    if horizon not in ("near", "med", "long"):
        raise HTTPException(status_code=400, detail=f"unknown horizon: {horizon!r}")
    if normalization_mode not in ("fixed", "rolling", "both"):
        raise HTTPException(status_code=400, detail=f"unknown normalization_mode: {normalization_mode!r}")

    start_date = start or _default_dates()[0]
    end_date = end or _default_dates()[1]
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start must be on or before end")

    factory = request.app.state.session_factory
    prices = CsvPriceProvider(_DEFAULT_PRICES)
    report = run_backtest(
        prices=prices,
        factory=factory,
        start=start_date,
        end=end_date,
        forward_days=forward_days,
        horizon=horizon,
        normalization_mode=normalization_mode,
    )
    return report.to_jsonable()
