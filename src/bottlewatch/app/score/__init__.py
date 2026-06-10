"""Bottleneck score package (M2).

Pure compute — no I/O, no DB session, no datetime.now() (callers pass
`now` in for testability). The recompute job wires this package to
the database; the FastAPI handlers read the materialized `scores`
table.

The pipeline:
  1. `extractors.capacity_tightness(segment, signals)` → the one
     sub-score that's computed from the `signals` table.
  2. `research_values.for_segment(segment)` → the four sub-scores
     that are hand-curated from M0 research.
  3. `normalize.normalize_5y(value, history)` → per-sub-score [0,1]
     mapping (only used for computed sub-scores with a time series;
     the research values are already in [0,1]).
  4. `formula.compute_segment_score(...)` → the full B(s, h) per
     research/04_scoring_methodology.md §1.
  5. `regime.classify(B, B', data_completeness)` → the 7-cell regime
     label (the 6 from §7.6 + NO_DATA).
"""

from bottlewatch.app.score.formula import (
    HORIZONS,
    ScoreResult,
    SubScore,
    compute_segment_score,
)
from bottlewatch.app.score.regime import REGIMES, Regime, classify

__all__ = [
    "HORIZONS",
    "REGIMES",
    "Regime",
    "ScoreResult",
    "SubScore",
    "classify",
    "compute_segment_score",
]
