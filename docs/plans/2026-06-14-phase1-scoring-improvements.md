# Plan: Phase 1 Scoring Improvements — Transparency + Live Signal Coverage

**Date:** 2026-06-14  
**Scope:** First milestone of the 3-phase scoring overhaul. Focus on honest data provenance, frozen regime thresholds, and wiring existing/almost-existing live signals into the score. Deliberately does **not** change normalization, HHI, or backtest infrastructure (those are Phase 2/3).

---

## 1. Decision points already resolved

| # | Question | Chosen option |
|---|---|---|
| 1 | HHI replacement | Phase 2: exposure × market-cap weighted HHI from `research/02_universe.csv` (not in this milestone). |
| 2 | Normalization | Phase 2: rolling 5-year bands behind a feature flag with parallel fixed-band comparison (not in this milestone). |
| 3 | Continue to next milestone without asking? | Yes. Phase 2 will start automatically after Phase 1 ships. |
| 4 | Multi-agent research for later phases? | Yes. |

---

## 2. Workstream A: Sub-score provenance and seed-share transparency

### 2.1 Problem

`Score.sub_scores` is a flat `dict[str, float | None]`. The API and UI show a single number with no indication whether it came from a live extractor, a static research seed, or an imputed default. Users see a precise score and assume it is measured.

### 2.2 Spec

**Inputs/outputs:**
- Input: the same 5 sub-score values already produced by `compute_segment_score()`.
- Output: a structured provenance record per sub-score plus a segment-level `static_seed_share` metric, persisted in the `scores` table and exposed in the API.

**Behavioral contract:**
- Every persisted sub-score carries `source ∈ {"extractor", "seed", "imputed"}`.
- `imputed` is used only for the current `None → 0.5` path (to be removed in Phase 2); in Phase 1 it marks values that had no source.
- `confidence ∈ {"high", "medium", "low"}`: high = live extractor with sufficient history; medium = live extractor with short/incomplete history; low = seed or imputed.
- `static_seed_share` per (segment, horizon) = fraction of the final weighted score that came from `source == "seed"` (by weighted contribution, not count).
- The UI must surface a warning when `static_seed_share > 0.5` for a segment/horizon.

**Error modes:**
- Legacy rows without provenance JSON degrade gracefully: treat all sub-scores as `source="seed"`, `confidence="low"`.
- A sub-score with a live value but missing history still gets `source="extractor"` and `confidence="medium"` or `"low"`.

**What this does NOT do:**
- Does not change how scores are computed (weights, normalization, imputation).
- Does not remove the `None → 0.5` substitution yet.
- Does not expose provenance on the scoreboard list by default; only on segment detail and a new hover/provenance drawer.

**Testable properties:**
- `SegmentDetail` API returns `sub_scores` as a dict of `{value, source, confidence}` for each of the 5 names.
- A segment with no dynamic extractors has `static_seed_share == 1.0` for all horizons.
- `power_generation_oem` with seeded capacity signals has `static_seed_share < 1.0`.
- The scoreboard shows a warning pill when `static_seed_share > 0.5`.

### 2.3 Implementation steps

1. Add `sub_score_provenance: Mapped[dict[str, Any]]` JSON column to `Score` model and an Alembic migration.
2. Add `static_seed_share: Mapped[float]` column to `Score` model and migration.
3. Refactor `ScoreResult` in `formula.py`:
   - Change `sub_scores: dict[str, float | None]` to a nested dataclass or keep backward-compat by also emitting `sub_score_provenance`.
   - Populate `source`, `confidence`, and `static_seed_share` during `compute_segment_score()`.
4. Update `ScoreResult.to_persisted()` to include the new columns.
5. Update API `SegmentScore` and `SegmentDetail` Pydantic models + `services.py` serialization.
6. Update frontend `SegmentDetail` page to render sub-score source/confidence badges.
7. Update `ScoreboardTable` to show a small warning icon when `static_seed_share > 0.5`.
8. Update all tests that assert `sub_scores` shape.

---

## 3. Workstream B: Freeze M2-v2 regime thresholds

### 3.1 Problem

The thresholds in `research/06_regime_thresholds.json` were tuned on the 2024-2026 window. Backtesting on the same window is circular. The methodology claims the thresholds are calibration constants, but there is no audit trail or explicit freeze.

### 3.2 Spec

**Inputs/outputs:**
- Input: existing `research/06_regime_thresholds.json`.
- Output: same JSON with `frozen_since` and a `changelog` array; updated methodology doc.

**Behavioral contract:**
- `regime.py` reads `frozen_since` for informational/logging purposes only; thresholds remain functional.
- Any future change must bump `version`, add a `changelog` entry with `date`, `reason`, and `commit` (optional), and only be justified on data after the change date.
- The recompute job logs the loaded threshold version once per run.

**What this does NOT do:**
- Does not change any threshold values in Phase 1.
- Does not add automated enforcement of the freeze beyond documentation and logging.

**Testable properties:**
- `research/06_regime_thresholds.json` contains `frozen_since`, `version`, and `changelog`.
- `regime.py` exposes a `THRESHOLDS_VERSION` constant matching the JSON `version`.
- The recompute log line includes the threshold version.

### 3.3 Implementation steps

1. Edit `research/06_regime_thresholds.json` to add `frozen_since: "2026-06-14"`, keep `version: "M2-v2"`, add `changelog` array.
2. Update `regime.py` to read and expose `frozen_since` and `changelog`.
3. Update `recompute_scores.py` to log threshold version.
4. Update methodology `research/04_scoring_methodology.md` §7.6 to state thresholds are frozen.
5. Add/update tests in `test_score_regime.py`.

---

## 4. Workstream C: Wire SEC EDGAR keyword counts into extractors

### 4.1 Problem

`sec_edgar.py` already emits `lead_time_mentions`, `shortage_mentions`, and `capacity_expansion_mentions` per ticker/filing, but `extractors.py` does not consume them. The data sits unused.

### 4.2 Spec

**Inputs/outputs:**
- Input: `signals` rows with `source="sec_edgar"`, `signal_name` in `{lead_time_mentions, shortage_mentions, capacity_expansion_mentions}`, mapped to a segment via `02_universe.csv`.
- Output: dynamic `lead_time_growth` and `capacity_tightness` sub-score overrides for segments covered by EDGAR filings.

**Behavioral contract:**
- Aggregate keyword counts per segment across all filings in the trailing 12 months.
- Compute a trailing-12-month z-score per segment: `z = (current_month_total - trailing_12mo_mean) / trailing_12mo_std`.
- Map `z ∈ [-2, +2]` to `[0, 1]` with 0 at -2, 0.5 at 0, 1 at +2; clamp outside the band.
- `lead_time_growth` uses `lead_time_mentions` (counts as a proxy for lead-time pressure language).
- `capacity_tightness` uses `shortage_mentions + capacity_expansion_mentions`.
- If fewer than 6 months of data exist, return `None` (fall back to seed).
- If `trailing_12mo_std == 0`, return `0.5` (no variation).

**Error modes:**
- A segment with no EDGAR-covered tickers returns `None`.
- Foreign-listed tickers (KS/TW/TSE) are already skipped by the adapter.

**What this does NOT do:**
- Does not extract new keywords (the keyword set is frozen).
- Does not weight filings by market cap or recency beyond the trailing-12-month window.
- Does not use EDGAR for `demand_signal` or `geo_concentration`.

**Testable properties:**
- A segment with rising mention counts over 12 months gets an extractor value > 0.5.
- A segment with flat/zero counts returns 0.5 or `None`.
- `transformers_tnd` and `power_generation_oem` gain dynamic signal from their universe tickers.

### 4.3 Implementation steps

1. In `extractors.py`, add `_edgar_keyword_score(signals, keyword_signal_names)` helper.
2. Add `_edgar_lead_time_growth(signals)` and `_edgar_capacity_tightness(signals)`.
3. Update `capacity_tightness()` and `lead_time_growth()` dispatchers to call the EDGAR extractors for all scoring segments (not just a subset).
4. In `recompute_scores.py`, pre-compute EDGAR-derived overrides per segment and pass them to `compute_segment_score()`.
5. Add unit tests in `test_score_extractors.py` with synthetic `_Row` signals.
6. Add/update integration tests in `test_recompute_scores.py`.

---

## 5. Workstream D: Remap Comtrade outputs to canonical segment slugs

### 5.1 Problem

`comtrade.py` writes `trade_volume` signals to non-canonical segment slugs: `hbm`, `lithography`, `transformers`. The scoring extractors never read them because they look for canonical slugs (`hbm_memory`, `transformers_tnd`, etc.).

### 5.2 Spec

**Inputs/outputs:**
- Input: existing Comtrade API response and `_COMMODITY_SPEC`.
- Output: `RawSignal.segment` set to canonical scoring slugs; new `capacity_tightness` extractor consuming `trade_volume` YoY.

**Behavioral contract:**
- HS 8541/8542 → `hbm_memory`
- HS 8486 → `advanced_packaging` (lithography equipment maps to packaging capacity for now; note this is a weak proxy and must be labeled LOW confidence)
- HS 8504 → `transformers_tnd`
- Compute YoY growth of monthly trade value; map `[-0.20, +0.40]` to `[0, 1]`; clamp outside.
- Require ≥13 months of history for YoY; otherwise return `None`.

**Error modes:**
- Missing Comtrade API key → adapter returns `[]` as today; no score impact.
- Gaps in Comtrade data → YoY computation uses the closest available 12-month-ago point; if none, return `None`.

**What this does NOT do:**
- Does not add new HS codes.
- Does not claim HS trade volume is a high-quality capacity proxy; confidence is LOW.
- Does not feed trade volume into `demand_signal`.

**Testable properties:**
- `ComtradeAdapter.fetch()` returns signals with canonical segment slugs.
- `capacity_tightness("hbm_memory", signals)` returns a value in [0,1] when 13+ months of `trade_volume` exist.
- `capacity_tightness("advanced_packaging", signals)` returns `None` for short history.

### 5.3 Implementation steps

1. Update `_COMMODITY_SPEC` in `comtrade.py` to use canonical segment slugs.
2. Add `_comtrade_capacity_tightness(signals)` in `extractors.py`.
3. Update `capacity_tightness()` dispatcher to route the three canonical segments.
4. Update `test_comtrade_adapter.py` segment assertions.
5. Add extractor tests in `test_score_extractors.py`.
6. Add integration tests in `test_recompute_scores.py`.

---

## 6. Workstream E: SEMI book-to-bill scraper

### 6.1 Problem

Semi segments (`advanced_node_fabs`, `hbm_memory`, `gpu_asic_silicon`, `networking_interconnect`, `advanced_packaging`) have no direct lead-time/capacity signal. SEMI publishes a monthly book-to-bill ratio for the semiconductor industry — a well-known leading indicator.

### 6.2 Spec

**Inputs/outputs:**
- Input: SEMI monthly book-to-bill press release (web scrape of `https://www.semi.org/en/market-info/statistics/semi-book-to-bill-report` or similar stable URL).
- Output: `book_to_bill_ratio` signal in `signals` table; `lead_time_growth` override for semi segments.

**Behavioral contract:**
- Scrape the latest monthly book-to-bill ratio and the historical table if available.
- Emit one `RawSignal` per month with `segment="advanced_node_fabs"` (canonical segment for the industry-level signal) and `signal_name="book_to_bill_ratio"`.
- The extractor maps `ratio ∈ [0.8, 1.4]` to `[0, 1]` with 1.0 at 1.4, 0.5 at 1.1, 0.0 at 0.8; clamp outside.
- `lead_time_growth()` dispatcher routes all semi segments to this extractor.
- Dead-letter handling: if scrape fails, write a `dead_letter` signal row (or log entry) and fall back to seed for two consecutive failures.
- Cadence: MONTHLY (SEMI releases ~mid-month).

**Error modes:**
- Layout change → scrape returns no rows; log warning, do not crash.
- Two consecutive failures → treat as unavailable and use seed.
- Missing historical table → emit only the latest point; extractor returns `None` until 1 point exists (it already needs only the latest level, not YoY).

**What this does NOT do:**
- Does not pay for SEMI WFF or segment-specific data.
- Does not use book-to-bill for `capacity_tightness` or `demand_signal`.

**Testable properties:**
- Adapter emits a `book_to_bill_ratio` signal when the page is mocked with a known HTML structure.
- `_semi_lead_time_growth()` returns ~0.83 for ratio=1.3.
- After two mocked failures, the extractor returns `None` (fallback to seed).

### 6.3 Implementation steps

1. Create `src/bottlewatch/app/ingest/semi_book_to_bill.py` with `SemiBookToBillAdapter` implementing the `Adapter` protocol.
2. Register it in `src/bottlewatch/app/ingest/__init__.py`.
3. Add `_semi_book_to_bill_lead_time_growth(signals)` in `extractors.py`.
4. Update `lead_time_growth()` dispatcher to use it for `_SEMI_SEGMENTS`.
5. Add `src/bottlewatch/tests/test_semi_book_to_bill_adapter.py` with mocked HTML.
6. Update `test_score_extractors.py` and `test_recompute_scores.py`.

---

## 7. Workstream F: Manual hyperscaler AI capex ledger

### 7.1 Problem

`demand_signal` is supposed to measure hyperscaler AI capex + IDC pre-lease + sovereign AI commitments. None of these are ingested. The methodology's most important demand driver is missing.

### 7.2 Spec

**Inputs/outputs:**
- Input: manually maintained JSON ledger at `research/06_capacity_ledger.json` (note: reuses `06_` prefix because it replaces the static ETA concept with a live-capacity/demand ledger; can be renamed if confusing).
- Output: `hyperscaler_ai_capex` signal and `demand_signal` override for relevant segments.

**Behavioral contract:**
- Ledger schema (per segment):
  ```json
  {
    "_comment": "...",
    "data_center_shell": {
      "signal_name": "hyperscaler_ai_capex",
      "unit": "USD_B",
      "entries": [
        {"ticker": "MSFT", "fiscal_quarter": "2025-Q3", "ai_capex_usd_b": 20.0, "source": "10-Q", "url": "...", "updated_by": "..."}
      ]
    }
  }
  ```
- Target tickers: MSFT, GOOG, AMZN, META, ORCL.
- Segments receiving the demand signal override: `data_center_shell`, `gpu_asic_silicon`, `advanced_node_fabs`, `hbm_memory`, `networking_interconnect`, `advanced_packaging`.
- Extractor computes trailing-4-quarter AI capex sum and YoY growth against the prior 4-quarter sum.
- Map YoY growth `[-0.10, +0.40]` to `[0, 1]`; clamp outside.
- Require ≥5 quarters of history (current + 4 prior) for a YoY; otherwise return `None`.
- Confidence is LOW because the ledger is manually maintained and AI-specific capex is approximate.

**Error modes:**
- Missing ledger file → extractor returns `None` for all segments.
- Missing quarter for a ticker → that quarter is excluded from the sum; if <4 quarters available, return `None`.
- Stale ledger (>45 days since most recent quarter update) → confidence drops to LOW (already default) and a warning is logged.

**What this does NOT do:**
- Does not auto-pull from EDGAR yet (that is Phase 2 or 3).
- Does not include sovereign AI commitments or IDC pre-lease.
- Does not use non-AI capex.

**Testable properties:**
- A ledger with 5 quarters of +30% YoY growth produces `demand_signal ≈ 1.0`.
- A ledger with flat growth produces `demand_signal ≈ 0.286` (same midpoint convention as other YoY extractors).
- Missing ledger file causes graceful fallback to seed.

### 7.3 Implementation steps

1. Create `research/06_capacity_ledger.json` with schema and seed entries for at least 4 recent quarters for the 5 target tickers.
2. Add `src/bottlewatch/app/score/capex_ledger.py` loader with validation.
3. Add `_hyperscaler_demand_signal(signals, ledger)` in `extractors.py`.
4. Update `demand_signal()` dispatcher to use it for the target segments.
5. In `recompute_scores.py`, load the ledger once and pass `demand_signal` override per segment.
6. Add unit tests in `test_score_extractors.py`.
7. Add integration tests in `test_recompute_scores.py`.
8. Document the manual-update operational burden in `research/04_scoring_methodology.md` and `README`.

---

## 8. Files to touch

| File | Change |
|---|---|
| `src/bottlewatch/app/db/models.py` | Add `sub_score_provenance`, `static_seed_share` columns to `Score`. |
| `alembic/versions/` | New migration for `Score` column additions. |
| `src/bottlewatch/app/score/formula.py` | Refactor `ScoreResult` / `SubScore` provenance; populate `static_seed_share`. |
| `src/bottlewatch/app/api/segments.py` | Update `SegmentScore`, `SegmentDetail` Pydantic models. |
| `src/bottlewatch/app/api/services.py` | Serialize new columns; legacy-row fallback. |
| `frontend/app/lib/api.ts` | Add `SubScoreValue`, provenance, `static_seed_share` fields. |
| `frontend/app/segment/[slug]/page.tsx` | Render source/confidence badges on sub-scores. |
| `frontend/app/components/ScoreboardTable.tsx` | Show seed-share warning icon. |
| `research/06_regime_thresholds.json` | Add `frozen_since`, `changelog`. |
| `src/bottlewatch/app/score/regime.py` | Read/expose `frozen_since`, `changelog`; log version. |
| `src/bottlewatch/jobs/recompute_scores.py` | Log threshold version; pre-compute new overrides. |
| `src/bottlewatch/app/ingest/sec_edgar.py` | No change unless the keyword→segment mapping needs fixing. |
| `src/bottlewatch/app/score/extractors.py` | Add EDGAR, Comtrade, SEMI, hyperscaler extractors and dispatchers. |
| `src/bottlewatch/app/ingest/comtrade.py` | Remap `_COMMODITY_SPEC` to canonical segments. |
| `src/bottlewatch/app/ingest/semi_book_to_bill.py` | New adapter. |
| `src/bottlewatch/app/ingest/__init__.py` | Register SEMI adapter. |
| `src/bottlewatch/app/score/capex_ledger.py` | New ledger loader. |
| `research/06_capacity_ledger.json` | New manual ledger. |
| `research/04_scoring_methodology.md` | Document provenance, frozen thresholds, new proxies, ledger ops burden. |
| `src/bottlewatch/tests/test_score_formula.py` | Update `sub_scores` assertions; add provenance tests. |
| `src/bottlewatch/tests/test_recompute_scores.py` | Add integration tests for new dynamic signals. |
| `src/bottlewatch/tests/test_score_extractors.py` | Add unit tests for new extractors. |
| `src/bottlewatch/tests/test_api_segments.py` | Update `sub_scores` shape assertions. |
| `src/bottlewatch/tests/test_comtrade_adapter.py` | Update canonical segment assertions. |
| `src/bottlewatch/tests/test_semi_book_to_bill_adapter.py` | New. |
| `src/bottlewatch/tests/test_capex_ledger.py` | New. |

---

## 9. Suggested implementation order

1. **Provenance DB columns + API + frontend warning** — highest user-value, touches many files, do first while context is fresh.
2. **Freeze thresholds** — tiny, independent.
3. **Comtrade segment remap** — small and self-contained.
4. **Hyperscaler capex ledger + extractor** — adds the most important missing demand signal.
5. **SEMI book-to-bill scraper + extractor** — adds semi lead-time signal.
6. **SEC EDGAR keyword wiring** — uses existing data; straightforward after extractors are warm.
7. **Full test sweep + docs update**.

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Provenance refactor breaks many tests | Update tests in the same PR; run `pytest` after each workstream. |
| Hyperscaler ledger becomes stale | Log warning if most recent entry is >45 days old; document 5-business-day update SLA. |
| SEMI scrape breaks on layout change | Dead-letter handling + two-failure fallback; unit tests use mocked HTML. |
| Comtrade HS codes are noisy proxies | Label confidence LOW; do not let trade volume override seed without review. |
| EDGAR keyword counts are unnormalized by document length | Use trailing-12-month z-score per segment, not raw counts. |
| Static seed share may still be high after Phase 1 | Expected. Phase 2/3 address HHI, normalization, and more primary sources. |

---

## 11. Success criteria for Phase 1

- [ ] `SegmentDetail` exposes sub-score `source`, `confidence`, and `static_seed_share`.
- [ ] Scoreboard warns when a segment/horizon is >50% static seed.
- [ ] Regime thresholds JSON has `frozen_since` and `changelog`.
- [ ] At least 3 new dynamic signals are wired into the score (Comtrade trade volume, SEMI book-to-bill, hyperscaler capex).
- [ ] SEC EDGAR keyword counts are consumed by `lead_time_growth` and/or `capacity_tightness` extractors.
- [ ] Dynamic signal share for the original 10 segments rises measurably (target: >40% of sub-score weighted contributions from extractors, up from ~20%).
- [ ] All CI checks pass: `ruff format --check`, `ruff check`, `pytest`, `pyright`, `make check-migrations`.
