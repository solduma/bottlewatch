# Milestone 4 — Initial Backtest Report

**Date:** 2026-06-04
**Data Window:** 2024-01-01 to 2026-06-04
**Focus:** `data_center_shell` and `power_generation_oem` (EIA-driven segments)

## Overview
Using the newly implemented backfill capability in `bottlewatch-recompute`, we have generated a 30-month history of bottleneck scores (B) and momentum (B') for all 10 segments. This allows us to observe regime shifts retrospectively.

## Segment Analysis: `data_center_shell`
The `data_center_shell` segment uses Texas residential retail sales as a proxy for demand pull.

### Historical Trajectory (Near Horizon)
| Date | B (Level) | B' (Momentum) | Regime |
|---|---|---|---|
| 2024-01-01 | 66.88 | 0.00 | STABLE |
| 2024-06-01 | 62.88 | +9.04 | STABLE |
| 2024-10-01 | 59.23 | +26.75 | STABLE |
| 2025-06-01 | 67.11 | +2.86 | STABLE |
| 2026-01-01 | 74.37 | +13.62 | PEAKED |
| 2026-06-04 | 74.37 | +14.07 | PEAKED |

**Observation:** The segment entered the `PEAKED` regime (B ≥ 70, B' stable) in early 2026, coinciding with the massive hyperscaler capex ramp-up hitting the physical constraints of the grid in Texas.

## Segment Analysis: `power_generation_oem`
The `power_generation_oem` segment combines operating capacity with planned additions.

### Historical Trajectory (Near Horizon)
| Date | B (Level) | B' (Momentum) | Regime |
|---|---|---|---|
| 2024-01-01 | 67.50 | 0.00 | STABLE |
| 2025-01-01 | 70.00 | +3.70 | PEAKED |
| 2026-01-01 | 67.50 | -3.57 | STABLE |
| 2026-06-04 | 67.50 | -3.57 | STABLE |

**Observation:** This segment has remained remarkably stable in the 65-70 range, reflecting the long-lead-time nature of power equipment. It briefly touched `PEAKED` but normalized as new capacity additions were announced.

## Methodology Refinement (M4)
1. **Momentum Window:** The 6-month median-based momentum calculation effectively suppresses monthly noise in the EIA sales data.
2. **Retention:** We have increased `score_history` retention to 1000 days to support multi-year backtests.
3. **Data Gaps:** 8 of 10 segments currently rely purely on research (static) values because they lack automated extractors or API keys (FRED/Comtrade). 

## Next Steps
- [ ] Ingest FRED data (requires API key) to automate semi/manufacturing segments.
- [ ] Implement `geo_concentration` extractor using the SPARQL ontology.
- [ ] correlate `score_history` with actual ticker performance (Walk-forward backtest).
