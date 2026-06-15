# Phase 3 Backtest Executive Summary

**Window:** 2024-09-01 to 2025-06-01  
**Horizon:** near  
**Forward return:** 90 days  
**Evaluation tuples:** 6990 across 10 dates  

## Headline results

- Overall IC: **0.032** (p=6.73e-03)
- Per-segment IC rows: 64
- Basket rebalances: 30
- Seed-share warning dates: 0

## Interpretation

The backtest is diagnostic, not a trading strategy. The overall Spearman IC is
small but statistically significant (p < 0.01) over the 9-month window,
suggesting the bottleneck score contains marginal forward-return information
when pooled across all segments and dates.

Per-segment IC rows, block-bootstrap confidence intervals, and
Benjamini-Hochberg correction are available in the full JSON report at
`data/reports/phase3_backtest.json`. Segments whose BH-corrected p-values are
rejected at FDR 10% are the most credible sources of signal.

Fixed-vs-rolling divergence is reported for every segment with common fixed and
rolling score-history points. Large mean absolute B differences or frequent
regime flips indicate that the rolling 5-year band is materially changing the
score. As `sub_score_history` matures, rolling bands should stabilize and the
divergence should shrink.

## Data caveats

- Prices are the placeholder `data/processed/prices.csv`; real price data will
  change basket returns materially.
- Only `ingested_at` is used as the point-in-time proxy; late revisions and
  backfills can still leak future information.
- Fixed and rolling bands use the current band configuration and universe;
  historical recomputes are not fully point-in-time on calibration.
