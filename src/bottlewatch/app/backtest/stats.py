"""Backtest statistics: date-level block-bootstrap inference and Benjamini-Hochberg.

The block bootstrap over per-date cross-sectional ICs is the single source of
truth for the point estimate, the confidence interval, *and* the p-value, so the
three are internally consistent. scipy is used only to compute each per-date
cross-sectional Spearman IC, not for any asymptotic p-value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class SegmentICResult:
    """Information coefficient result for one segment.

    `rho` is None when fewer than 2 usable eval dates remain (cannot
    bootstrap a distribution of dates); otherwise it is the mean of the
    per-date cross-sectional ICs.
    """

    segment: str
    n: int
    rho: float | None
    p_value: float | None
    ci_low: float | None
    ci_high: float | None
    bh_rejected: bool


@dataclass(frozen=True)
class BootstrapResult:
    """Result of a date-level block-bootstrap over per-date ICs.

    `mean`/`ci_low`/`ci_high`/`p_value` are None when fewer than 2 usable
    eval dates remain (no bootstrap distribution is possible).
    """

    n_bootstraps: int
    n_dates: int
    mean: float | None
    std: float | None
    ci_low: float | None
    ci_high: float | None
    p_value: float | None


def block_size_for(forward_days: int, step_days: int) -> int:
    """Bootstrap block size = ceil(forward_days / step_days).

    Consecutive eval dates step `step_days` apart but the forward-return
    window spans `forward_days`, so ~ceil(forward_days/step_days) consecutive
    date-ICs share return path. Resampling contiguous blocks of that length
    preserves the overlap. Default 90/30 = 3.
    """
    if step_days <= 0:
        raise ValueError("step_days must be positive")
    return max(1, math.ceil(forward_days / step_days))


def _per_date_ic(points: Sequence[tuple[float, float]]) -> float | None:
    """Cross-sectional Spearman IC over one date's (B, return) pairs.

    Returns None when the date is degenerate (< 4 points or no variance).
    """
    if len(points) < 4:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    spearman_result: Any = stats.spearmanr(xs, ys)
    rho = float(spearman_result.statistic)
    return None if np.isnan(rho) else rho


def _block_bootstrap_ic(
    eval_dates: Sequence[Any],
    points_by_date: dict[Any, list[tuple[float, float]]],
    block_size: int = 3,
    n_bootstraps: int = 1000,
    seed: int = 42,
) -> BootstrapResult:
    """Date-level block-bootstrap of the mean cross-sectional IC.

    Collapses pseudo-replication: the unit of observation is the per-date IC,
    not the (ticker, date) tuple. The point estimate is the mean of the per-date
    ICs; the CI is the 2.5/97.5 percentiles of the bootstrap distribution of
    that mean; the p-value is the two-sided bootstrap p for H0: mean IC = 0,
    `2 * min(share <= 0, share >= 0)` floored at `1/n_bootstraps`.
    """
    # Per-date ICs in eval-date order, keeping only non-degenerate dates.
    date_ics: list[float] = []
    for d in eval_dates:
        ic = _per_date_ic(points_by_date.get(d, []))
        if ic is not None:
            date_ics.append(ic)

    n_dates = len(date_ics)
    if n_dates < 2:
        # Cannot bootstrap a distribution from fewer than 2 dates.
        return BootstrapResult(
            n_bootstraps=0,
            n_dates=n_dates,
            mean=None,
            std=None,
            ci_low=None,
            ci_high=None,
            p_value=None,
        )

    point_estimate = float(np.mean(date_ics))

    rng = np.random.default_rng(seed)
    boot_means: list[float] = []
    for _ in range(n_bootstraps):
        # Resample contiguous blocks of per-date ICs to preserve overlap.
        block_starts = rng.integers(0, n_dates, size=n_dates)
        sample: list[float] = []
        for start in block_starts:
            for offset in range(block_size):
                sample.append(date_ics[(start + offset) % n_dates])
        boot_means.append(float(np.mean(sample)))

    arr = np.array(boot_means)
    ci_low, ci_high = float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))
    share_le = float(np.mean(arr <= 0.0))
    share_ge = float(np.mean(arr >= 0.0))
    p_value = max(2.0 * min(share_le, share_ge), 1.0 / n_bootstraps)
    return BootstrapResult(
        n_bootstraps=n_bootstraps,
        n_dates=n_dates,
        mean=point_estimate,
        std=float(np.std(arr, ddof=1)),
        ci_low=ci_low,
        ci_high=ci_high,
        p_value=p_value,
    )


def benjamini_hochberg(
    p_values: Sequence[tuple[str, float | None]],
    alpha: float = 0.10,
) -> dict[str, bool]:
    """Return which hypotheses are rejected at FDR `alpha`.

    Input is a list of (label, p_value). None p-values are treated as
    1.0 (not rejected). BH procedure rejects hypotheses whose sorted
    p-value p_(i) <= i * alpha / m.
    """
    labeled = [(label, 1.0 if p is None else p) for label, p in p_values]
    m = len(labeled)
    if m == 0:
        return {}
    sorted_by_p = sorted(labeled, key=lambda t: t[1])
    rejected_labels: set[str] = set()
    # Find largest k such that p_(k) <= k * alpha / m.
    threshold_index = 0
    for i, (label, p) in enumerate(sorted_by_p, start=1):
        if p <= i * alpha / m:
            threshold_index = i
    if threshold_index > 0:
        for label, _ in sorted_by_p[:threshold_index]:
            rejected_labels.add(label)
    return {label: label in rejected_labels for label, _ in labeled}


def date_level_ic(
    eval_dates: Sequence[Any],
    points_by_date: dict[Any, list[tuple[float, float]]],
    forward_days: int,
    step_days: int,
    n_bootstraps: int = 1000,
    seed: int = 42,
) -> BootstrapResult:
    """Date-level block-bootstrap IC with block size derived from forward/step."""
    return _block_bootstrap_ic(
        eval_dates,
        points_by_date,
        block_size=block_size_for(forward_days, step_days),
        n_bootstraps=n_bootstraps,
        seed=seed,
    )


def segment_ic_with_ci(
    segment: str,
    n: int,
    eval_dates: Sequence[Any],
    points_by_date: dict[Any, list[tuple[float, float]]],
    forward_days: int,
    step_days: int,
) -> SegmentICResult:
    """Date-level bootstrap IC, CI, and bootstrap p-value for one segment.

    `n` is the number of (ticker, date) eval points (carried through for
    disclosure only; the inference is date-level). The BH flag is set by the
    caller after the multiple-comparison correction.
    """
    bootstrap = date_level_ic(eval_dates, points_by_date, forward_days, step_days)
    return SegmentICResult(
        segment=segment,
        n=n,
        rho=bootstrap.mean,
        p_value=bootstrap.p_value,
        ci_low=bootstrap.ci_low,
        ci_high=bootstrap.ci_high,
        bh_rejected=False,  # set by caller after BH correction
    )
