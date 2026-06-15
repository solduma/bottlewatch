"""Backtest statistics: block-bootstrap CIs and Benjamini-Hochberg correction.

Light wrapper around scipy so the backtest job stays readable.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any

import numpy as np
from scipy import stats


@dataclass(frozen=True)
class SegmentICResult:
    """Information coefficient result for one segment."""

    segment: str
    n: int
    rho: float
    p_value: float | None
    ci_low: float | None
    ci_high: float | None
    bh_rejected: bool


@dataclass(frozen=True)
class BootstrapResult:
    """Result of a block-bootstrap over evaluation dates."""

    n_bootstraps: int
    mean: float
    std: float
    ci_low: float
    ci_high: float


def _block_bootstrap_ic(
    eval_dates: Sequence[Any],
    points_by_date: dict[Any, list[tuple[float, float]]],
    block_size: int = 3,
    n_bootstraps: int = 1000,
    seed: int = 42,
) -> BootstrapResult:
    """Block-bootstrap Spearman IC over evaluation dates.

    Preserves serial correlation by resampling contiguous blocks of
    evaluation dates.
    """
    rng = np.random.default_rng(seed)
    n_dates = len(eval_dates)
    if n_dates == 0:
        return BootstrapResult(n_bootstraps=0, mean=0.0, std=0.0, ci_low=0.0, ci_high=0.0)

    ics: list[float] = []
    for _ in range(n_bootstraps):
        # Sample block starting indices with replacement.
        block_starts = rng.integers(0, n_dates, size=n_dates)
        xs: list[float] = []
        ys: list[float] = []
        for start in block_starts:
            for offset in range(block_size):
                idx = (start + offset) % n_dates
                d = eval_dates[idx]
                for x, y in points_by_date.get(d, []):
                    xs.append(x)
                    ys.append(y)
        if len(xs) < 4 or len(set(xs)) < 2 or len(set(ys)) < 2:
            continue
        spearman_result: Any = stats.spearmanr(xs, ys)
        rho = float(spearman_result.statistic)
        if not np.isnan(rho):
            ics.append(rho)

    if not ics:
        return BootstrapResult(n_bootstraps=n_bootstraps, mean=0.0, std=0.0, ci_low=0.0, ci_high=0.0)

    arr = np.array(ics)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    ci_low, ci_high = float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))
    return BootstrapResult(
        n_bootstraps=n_bootstraps,
        mean=mean,
        std=std,
        ci_low=ci_low,
        ci_high=ci_high,
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


def segment_ic_with_ci(
    segment: str,
    xs: Sequence[float],
    ys: Sequence[float],
    eval_dates: Sequence[Any],
    points_by_date: dict[Any, list[tuple[float, float]]],
    alpha: float = 0.10,
) -> SegmentICResult:
    """Compute Spearman IC, p-value, block-bootstrap CI, and BH flag."""
    n = len(xs)
    if n < 4 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return SegmentICResult(
            segment=segment,
            n=n,
            rho=0.0,
            p_value=None,
            ci_low=None,
            ci_high=None,
            bh_rejected=False,
        )
    spearman_result: Any = stats.spearmanr(xs, ys)
    rho = float(spearman_result.statistic)
    p_value = float(spearman_result.pvalue) if spearman_result.pvalue is not None else None
    bootstrap = _block_bootstrap_ic(eval_dates, points_by_date)
    return SegmentICResult(
        segment=segment,
        n=n,
        rho=rho,
        p_value=p_value,
        ci_low=bootstrap.ci_low,
        ci_high=bootstrap.ci_high,
        bh_rejected=False,  # set by caller after BH correction
    )
