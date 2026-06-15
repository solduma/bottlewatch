# Plan: Phase 3 — Backtest Validation + Basket Engine

**Date:** 2026-06-14  
**Scope:** Third milestone of the 3-phase scoring overhaul. Validate the scoring pipeline with a point-in-time walk-forward backtest, build the ticker-level conviction basket engine from methodology §7.9, and add statistical diagnostics. This plan explicitly does **not** add new primary data sources (EIA ISO/RTO, Form 4, etc.) — those are deferred to a follow-up data-coverage phase.

---

## 1. Decision points already resolved

| # | Question | Chosen option |
|---|---|---|
| 1 | Backtest goal | Diagnostic only, not a trading strategy. Flag rows with >80% static seed share. |
| 2 | Statistical rigor | Block-bootstrap confidence intervals for IC and Benjamini-Hochberg correction for multiple segments. |
| 3 | Fixed vs rolling comparison | Run both `SCORE_NORMALIZATION_MODE=fixed` and `rolling` in parallel during the backtest, report divergence. |
| 4 | Point-in-time signals | Use `ingested_at` as the as-of proxy; filter `observed_at <= t` and `ingested_at <= t` for each recompute date `t`. Document the limitation. |
| 5 | Universe snapshots | Short-term: support dated universe CSVs via `--universe` path. Long-term: defer `universe_history` table. |
| 6 | Basket construction | Implement methodology §7.9 long/short/watchlist baskets at the ticker level using the existing `02_universe.csv` + price CSV. |
| 7 | Output artifact | JSON backtest report consumed by a new `/api/v1/backtest` endpoint + an executive-summary notebook under `notebooks/`. |

---

## 2. Workstream A: Point-in-time recompute plumbing

### 2.1 Problem

The current `bottlewatch-recompute --backfill-since` filters signals only by `observed_at`. Late-arriving revisions and backfills leak future information into historical scores. Phase 3 needs an `as_of` recompute mode.

### 2.2 Spec

**Inputs/outputs:**
- Input: an `as_of: datetime` and a `normalization_mode: str`.
- Output: a full set of `scores`, `score_history`, and `sub_score_history` rows as they would have been computed on that date.

**Behavioral contract:**
- `_load_signals_by_segment(factory, since, until, as_of)` accepts an optional `as_of` parameter.
- When `as_of` is provided, the query additionally filters `Signal.ingested_at <= as_of` and `Signal.observed_at <= as_of.date()`.
- `score_history` and `sub_score_history` used for momentum/rolling bands are also filtered to `computed_at <= as_of`.
- The function remains pure: it returns a `RunReport`; the caller decides whether to write to a temp DB or a dry-run DB.
- The existing daily recompute path keeps its current behavior (no `as_of` filter) so production is unchanged.

**Error modes:**
- `as_of` before the first signal ingestion → scores fall back to seeds (same as a fresh DB).
- Missing `ingested_at` on legacy rows → those rows are excluded from point-in-time recomputes; log a warning.

### 2.3 Files to touch

- Modify: `src/bottlewatch/jobs/recompute_scores.py`
  - `_load_signals_by_segment()` adds `as_of: datetime | None = None`.
  - `_load_score_history()` and `_load_sub_score_history()` add `as_of` filter.
  - `run()` adds `as_of: datetime | None = None` and passes it through.
- Tests: `src/bottlewatch/tests/test_recompute_scores.py`

---

## 3. Workstream B: Basket engine

### 3.1 Problem

The screener is segment-level only. The methodology §7.9 calls for ticker-level conviction baskets: top 1-2 segments → top 3-5 tickers by `exposure_pct × segment_score`.

### 3.2 Spec

**Inputs/outputs:**
- Input: a date `t`, a horizon, a side (`long` | `short` | `watchlist`), the current `scores`/`score_history`, and the universe CSV.
- Output: a `Basket` dataclass containing segment-level selections, ticker-level selections, equal-weight forward-return estimate, and basket metadata.

**Behavioral contract:**
- Long basket:
  1. Segments with `B >= 50`.
  2. Exclude `RESOLVING`, `RESOLVING_FROM_LOW`, `NO_DATA` (hard guard).
  3. Sort by `B` desc, then `B'` desc.
  4. Select top 1-2 segments. A second segment is included only if its score is within 10 points of the top segment.
  5. For each selected segment, take tickers with `exposure_pct >= 50` and `mcap_usd >= 2B`.
  6. Rank tickers by `exposure_pct × B`; take top 3-5 per segment.
  7. Combine and dedupe by ticker; equal-weight.
- Short basket:
  1. Segments with `B >= 50` and regime == `RESOLVING`.
  2. Sort by `B × abs(B')` desc.
  3. Select top 1-2 segments.
  4. Same ticker filters and ranking as long.
- Watchlist:
  1. `EMERGING` or `PEAKED` with `B >= 50`.
  2. No position sizing; just list tickers.
- Forward return for a basket is the equal-weight mean of `close[t + N] / close[t] - 1` over selected tickers. Missing prices are excluded from the mean and counted as "coverage".
- If no tickers pass filters, the basket is empty and return is `None`.

### 3.3 Files to touch

- New: `src/bottlewatch/app/backtest/baskets.py`
- New: `src/bottlewatch/app/backtest/basket_report.py`
- Modify: `src/bottlewatch/app/api/screener.py` to optionally use the basket engine (or keep it segment-level; no change required).
- Tests: `src/bottlewatch/tests/test_backtest_baskets.py`

---

## 4. Workstream C: Backtest report + statistics

### 4.1 Problem

The existing backtest computes Spearman correlation between segment scores and forward returns. Phase 3 needs:
- Ticker-level basket returns over time.
- Fixed vs rolling band comparison.
- Block-bootstrap CIs for IC.
- Benjamini-Hochberg correction when testing many segments.

### 4.2 Spec

**Inputs/outputs:**
- Input: `--start`, `--end`, `--eval-frequency` (monthly default), `--forward-days`, `--horizon`, `--normalization-mode` (or `both`), `--universe`, `--prices`.
- Output: JSON report with sections below.

**Behavioral contract:**
- Evaluation dates: first-of-month from `--start` to `--end`.
- For each eval date `t`:
  - Recompute scores with the chosen normalization mode and `as_of=t`.
  - Build long/short/watchlist baskets.
  - Compute forward returns over `--forward-days` trading days.
  - Record per-segment Spearman(B, forward return) for that date.
- Aggregations:
  - Overall IC (Spearman) and t-stat across all (ticker, segment, t) tuples.
  - Per-segment IC, with block-bootstrap 95% CI (bootstrap over evaluation dates, preserve autocorrelation by sampling contiguous date blocks).
  - BH-corrected p-values across segments; flag false-discovery rate < 10%.
  - Basket cumulative return curve and summary stats (total return, annualized Sharpe, max drawdown, hit rate).
  - Fixed-vs-rolling divergence: mean absolute difference in B per segment, count of regime flips.
- Seed-share warning: list dates where >50% of baskets have `static_seed_share > 0.80`.

**Statistical implementation:**
- Add `scipy` to `pyproject.toml` `[project.dependencies]` for Spearman p-values, t-distribution, and bootstrap.
- Use `scipy.stats.spearmanr` and `scipy.stats.t`.
- Block bootstrap: sample blocks of 3-month evaluation windows with replacement; compute Spearman on each resample.
- BH correction: rank p-values, threshold = `i * alpha / m`.

### 4.3 Files to touch

- Modify: `src/bottlewatch/jobs/backtest.py`
- Modify: `src/bottlewatch/app/backtest/stats.py` (new file for bootstrap + BH)
- Modify: `pyproject.toml`
- Tests: `src/bottlewatch/tests/test_backtest.py`, `src/bottlewatch/tests/test_backtest_stats.py`

---

## 5. Workstream D: API + frontend surface

### 5.1 Changes

- New API endpoint `GET /api/v1/backtest/report`:
  - Query params: `start`, `end`, `horizon`, `forward_days`, `normalization_mode`.
  - Returns the JSON report (or a cached path if computation is heavy).
  - Implementation lives in a new `src/bottlewatch/app/api/backtest.py`.
- Frontend:
  - Add `BacktestReport` type to `frontend/app/lib/api.ts`.
  - Add a simple `/backtest` page that fetches the report and renders:
    - Cumulative return curves for long/short baskets.
    - IC table with CIs and BH stars.
    - Fixed vs rolling divergence heatmap.
    - Seed-share warning banner.

### 5.2 Files to touch

- New: `src/bottlewatch/app/api/backtest.py`
- New: `frontend/app/backtest/page.tsx`
- Modify: `frontend/app/lib/api.ts`, `src/bottlewatch/app/main.py` (register router)
- Tests: `src/bottlewatch/tests/test_api_backtest.py`

---

## 6. Workstream E: Notebook + executive summary

### 6.1 Changes

- Create `notebooks/phase3_backtest_report.ipynb` that:
  - Loads a pre-computed backtest JSON.
  - Plots basket cumulative returns, IC distribution, fixed-vs-rolling divergence.
  - Writes a markdown executive summary to `docs/plans/2026-06-14-phase3-executive-summary.md`.
- The notebook is the primary research artifact; the API report is the machine-readable version.

### 6.2 Files to touch

- New: `notebooks/phase3_backtest_report.ipynb`
- New: `docs/plans/2026-06-14-phase3-executive-summary.md` (placeholder)

---

## 7. Workstream F: Price data stub

### 7.1 Problem

`data/processed/prices.csv` does not exist. Phase 3 needs at least a minimal price file to run the backtest.

### 7.2 Spec

- Create a synthetic/placeholder price CSV at `data/processed/prices.csv` with columns `ticker,date,close`.
- Populate it with one row per universe ticker per month from 2024-01 to 2026-06 using a deterministic random-walk seeded by ticker + date, so tests are reproducible.
- Mark the file clearly as a **placeholder** in a README; real price ingestion is deferred.
- The backtest job should still work if a real `prices.csv` is supplied via `--prices`.

### 7.3 Files to touch

- New: `data/processed/prices.csv`
- New: `data/processed/prices.README.md`
- New script: `research/scripts/generate_placeholder_prices.py`
- Tests: update `test_backtest.py` to use the placeholder.

---

## 8. Out of scope

- New primary data sources (Form 4, EIA ISO/RTO, vendor prices).
- `universe_history` table (use dated CSVs instead).
- `released_at` signal column (use `ingested_at` proxy).
- Real-money position sizing / transaction costs.

---

## 9. Test plan

- Unit: basket construction with mock scores and universe.
- Unit: block-bootstrap CI and BH correction with known synthetic data.
- Integration: point-in-time recompute excludes future `ingested_at` signals.
- Integration: full backtest CLI runs against placeholder prices and produces JSON.
- API: `/api/v1/backtest/report` returns a valid report.
- Frontend: TypeScript compiles; `/backtest` page renders without errors.

---

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| No real price data | Synthetic placeholder with documented limitations; backtest is diagnostic only. |
| Point-in-time leaks through universe/seed/calibration | Document that only signals are point-in-time; universe and bands are current. |
| `scipy` adds dependency | It is the standard scientific stack and justified for backtest statistics. |
| Rolling bands need 2y history | Default to `fixed` for short windows; `rolling` only meaningful after backfill. |
| Multiple-segment false discoveries | BH correction + block-bootstrap CIs surface uncertainty honestly. |

---

## 11. Definition of done

- `bottlewatch-backtest --normalization-mode both --output report.json` runs successfully against placeholder prices.
- `/api/v1/backtest/report` returns the report.
- `/backtest` page renders cumulative returns and IC table.
- `notebooks/phase3_backtest_report.ipynb` executes end-to-end and writes the executive summary.
- `make test`, `ruff check`, `ruff format --check`, `pyright`, and `make check-migrations` all pass.
