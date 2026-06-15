# Plan: Phase 2 Scoring Improvements — HHI + Raw Extractors + Rolling Normalization

**Date:** 2026-06-14  
**Scope:** Second milestone of the 3-phase scoring overhaul. Replaces the ontology HHI, refactors extractors to emit raw values, and introduces a centralized `SubScoreNormalizer` with rolling 5-year bands behind a feature flag. This plan covers the scoring-engine refactor; new primary data sources (EIA ISO/RTO, point-in-time gating) are deferred to a follow-up once the engine is stable.

---

## 1. Decision points already resolved

| # | Question | Chosen option |
|---|---|---|
| 1 | HHI replacement | **Replace immediately** with exposure × market-cap weighted HHI from `research/02_universe.csv`, plus curated `operatesIn` overrides. Keep ontology path as opt-in fallback. |
| 2 | Normalization | **Rolling 5-year bands behind a feature flag** with parallel fixed-band comparison. Default remains fixed bands until sub-score history matures. |
| 3 | `None → 0.5` substitution | Move the imputation into the normalizer and flag it explicitly in provenance; remove the silent substitution from `formula.py`. |
| 4 | Persist sub-score bands | Yes — add a `sub_score_history` table and store both raw and normalized values in the `scores` table. |
| 5 | Continue without asking? | Yes, per user approval on 2026-06-14. |

---

## 2. Workstream A: Replace ontology HHI with universe-weighted HHI

### 2.1 Problem

The current `geo_concentration` sub-score is derived from an OWL ontology (`research/05_ontology/`). It counts role instances per region and computes HHI from those counts. That HHI is not weighted by economic exposure or market cap, and the ABox geography is mostly inferred from listing exchange, which over-assigns non-US companies to `NorthAmerica` when they have a US ADR.

### 2.2 Spec

**Inputs/outputs:**
- Input: `research/02_universe.csv` (columns include `ticker`, `exchange`, `name`, `segment`, `exposure_pct`, `mcap_usd`, `notes`) and a new curated override file `research/07_geo_overrides.json`.
- Output: a single `geo_concentration` value in `[0, 1]` per segment, with the same provenance shape as other sub-scores.

**Behavioral contract:**
- A segment's HHI is computed from the **exposure_pct × mcap_usd** weights of all universe rows belonging to that segment.
- Rows are grouped by canonical company. The default grouping key is `ticker`; `research/07_geo_overrides.json` may define a `parent` for rows that represent the same economic entity under different listings (e.g., `TSM` and `2330.TW`), in which case weights are summed under the parent.
- Region assignment order: (1) override in `research/07_geo_overrides.json`, (2) exchange → region map shared with the ontology builder, (3) unknown region. Rows with unknown region are dropped.
- The methodology's 5% share floor is applied: regions with share < 5% are dropped and the remainder is renormalized before computing HHI.
- If the resulting HHI diverges from the research seed by more than `0.30` (absolute), keep the **seed** value and mark provenance `source="seed"`, `confidence="low"`, with a `divergence` note. This prevents a noisy universe calculation from flipping the score while the override file is still being curated.
- If no universe rows exist for a segment, fall back to the seed value.
- The ontology path remains available via `GEO_CONCENTRATION_SOURCE=ontology` for comparison.

**Error modes:**
- Missing or malformed CSV → log warning, fall back to seed for all segments.
- Missing override file → treat as empty (no overrides).
- Duplicate parent/ticker conflicts in overrides → first entry wins, log warning.

### 2.3 Files to touch

- New: `src/bottlewatch/app/score/geo.py`
- New: `research/07_geo_overrides.json`
- Modify: `src/bottlewatch/jobs/build_ontology.py` (import exchange→region map from `geo.py`)
- Modify: `src/bottlewatch/jobs/recompute_scores.py` (branch on `settings.geo_concentration_source`)
- Modify: `src/bottlewatch/config.py` (`geo_concentration_source` setting)
- Tests: `src/bottlewatch/tests/test_score_geo.py`
- Docs: `research/04_scoring_methodology.md` §2.3

---

## 3. Workstream B: Extractors emit raw values

### 3.1 Problem

Every extractor currently clamps its output to `[0, 1]` using hard-coded bands. That makes rolling normalization impossible: we lose the original raw metric and cannot re-compute historical normalized values as the 5-year band expands.

### 3.2 Spec

**Inputs/outputs:**
- Input: unchanged (segment slug + signals iterator).
- Output: each extractor returns a **raw value** (`float | None`) and a **source key** string identifying the source/band to use for normalization.

**Behavioral contract:**
- `capacity_tightness`, `demand_signal`, and `lead_time_growth` extractors return raw values in their natural units (PPI level, YoY ratio, capacity ratio, z-score, HHI, etc.) and a source key.
- `geo_concentration` returns the already-normalized HHI in `[0, 1]`; its source key is `"hhi"`.
- Research seed values remain in `[0, 1]`; they are treated as already-normalized and bypass fixed-band normalization (band min=0, max=1).
- The caller (`recompute_scores` or `formula`) passes the raw value + source key to the normalizer.
- Existing unit tests for extractor band behavior are replaced with tests that assert the correct raw value and source key; normalization tests move to `test_score_normalize.py`.

**Source keys returned by extractors:**
- `lead_time_growth.transformers_tnd` → `"transformers_ppi"` (raw PPI level)
- `lead_time_growth.*` semi book-to-bill → `"semi_book_to_bill"`
- `lead_time_growth.*` semi PPI fallback → `"semi_ppi"`
- `lead_time_growth.*` EDGAR fallback → `"edgar_keyword"` (z-score)
- `demand_signal.transformers_tnd` → `"transformer_orders"` (YoY)
- `demand_signal.*` hyperscaler ledger → `"hyperscaler_capex"` (YoY)
- `demand_signal.*` manufacturing INDPRO → `"manufacturing_indpro"`
- `capacity_tightness.power_generation_oem` → `"power_ratio"`
- `capacity_tightness.data_center_shell` → `"retail_sales_yoy"`
- `capacity_tightness.*` manufacturing → `"manufacturing_utilization"`
- `capacity_tightness.*` Comtrade → `"comtrade_volume"`
- `capacity_tightness.*` EDGAR fallback → `"edgar_keyword"`
- `geo_concentration.*` → `"hhi"`

### 3.3 Files to touch

- Modify: `src/bottlewatch/app/score/extractors.py` (return raw values + source keys)
- Modify: `src/bottlewatch/app/score/formula.py` (consume raw values, delegate normalization)
- Tests: update `test_score_extractors.py`, `test_score_formula.py`
- Docs: `research/04_scoring_methodology.md` §2.1-2.2

---

## 4. Workstream C: Centralized rolling normalization

### 4.1 Problem

`normalize_5y()` exists but is unused in production. Every extractor hard-codes its own band, which creates the "illusion of dynamic precision" and prevents historical backtesting because old recomputes cannot be re-normalized with today's expanded history.

### 4.2 Spec

**Inputs/outputs:**
- Input: sub-score name, raw value, source key, normalization mode (`"fixed"` | `"rolling"`), optional trailing history (`list[float]`), and the band configuration JSON.
- Output: a `NormalizedSubScore` dataclass containing `value` (in `[0, 1]`), `raw_value`, `source`, `confidence`, `imputed`, `normalization_mode`, `band_min`, `band_max`.

**Behavioral contract:**
- `mode="fixed"`: look up the band for `(sub_score_name, source_key)` in `research/config/score_bands.json`. Map raw value linearly from `[min, max]` to `[0, 1]` and clamp. This reproduces the current behavior for all existing extractors.
- `mode="rolling"`: if the trailing history spans at least 2 years, winsorize at the 5th and 95th percentiles of the history, use those as the band, and map the raw value. If history is shorter than 2 years or has zero variance, fall back to the fixed band and record `normalization_mode="fallback_to_fixed"`.
- When `raw` is `None`, return `value=0.5` (universe median placeholder), `source="imputed"`, `imputed=True`, `confidence="low"`, and use the fixed band for audit. This replaces the silent substitution in `formula.py`.
- When the source is a research seed (`source_key="seed"`), `value=raw`, `source="seed"`, `imputed=False`, `confidence="low"`; normalization is a no-op.
- When a rolling band exceeds the fixed band by more than 2× on either side, log a calibration warning. This surfaces cases where the fixed band was badly chosen.
- Confidence rules:
  - `high`: live extractor value, fixed mode OR rolling mode with ≥2 years history.
  - `medium`: live extractor value, rolling mode with ≥1 year but <2 years history.
  - `low`: seed value, imputed value, or rolling mode with <1 year history / fallback to fixed.

**Band configuration file:**
- Path: `research/config/score_bands.json`
- Same shape as `research/06_regime_thresholds.json`: `_comment`, `version`, `frozen_since`, `changelog`, and a `bands` dict keyed by sub-score, then by source key.
- Example entries:
  - `"lead_time_growth"."transformers_ppi": {"type": "level", "min": 80.0, "max": 350.0}`
  - `"lead_time_growth"."semi_book_to_bill": {"type": "level", "min": 0.8, "max": 1.4}`
  - `"capacity_tightness"."power_ratio": {"type": "ratio", "min": 0.0, "max": 1.0}`
  - `"demand_signal"."hyperscaler_capex": {"type": "yoy", "min": -0.10, "max": 0.40}`

### 4.3 Files to touch

- New: `research/config/score_bands.json`
- New/modify: `src/bottlewatch/app/score/normalize.py` (`SubScoreNormalizer`, `NormalizedSubScore`, `normalize_subscore`)
- Modify: `src/bottlewatch/app/score/formula.py` (use normalizer, remove silent substitution)
- Modify: `src/bottlewatch/config.py` (`score_normalization_mode` setting)
- Tests: `src/bottlewatch/tests/test_score_normalize.py`
- Docs: `research/04_scoring_methodology.md` §1, §2.x

---

## 5. Workstream D: Persist sub-score history

### 5.1 Problem

Rolling normalization needs a history of **raw sub-score values**, but the current `score_history` table only stores final `B` scores. Without a persisted history, recomputing old scores with today's expanded band is impossible, and backtests cannot be point-in-time.

### 5.2 Spec

**Schema:**
- New table `sub_score_history` (Alembic revision `0007_add_sub_score_history`):
  - `id` PK autoincrement
  - `segment` str not null
  - `sub_score_name` str not null
  - `computed_at` datetime not null
  - `raw_value` float nullable
  - `normalized_value` float nullable
  - `normalization_mode` str nullable (fixed | rolling | fallback_to_fixed)
  - `band_min` float nullable
  - `band_max` float nullable
  - `history_span_days` int nullable
  - Index `(segment, sub_score_name, computed_at)`
- Add to `scores` table:
  - `raw_sub_scores` JSON nullable — stores the raw values before normalization, one per sub-score.
  - `normalization_mode` str nullable — the mode active when this row was computed.

**Behavioral contract:**
- Every recompute run writes one `sub_score_history` row per `(segment, sub_score_name)`.
- `--backfill-since` populates the table month-by-month, giving a history trail that can mature into 5-year rolling bands.
- The normalizer reads the trailing 5 years of `sub_score_history.raw_value` per `(segment, sub_score_name)` when `mode="rolling"`.
- `score_history` retention remains 1000 days (reconcile the docstring/code drift: code wins). `sub_score_history` uses the same retention.
- A `score_band_version` log line is emitted by the recompute job, mirroring the existing `THRESHOLDS_VERSION` logging.

### 5.3 Files to touch

- New migration: `alembic/versions/0007_add_sub_score_history.py`
- Modify: `src/bottlewatch/app/db/models.py` (`SubScoreHistory`, add columns to `Score`)
- Modify: `src/bottlewatch/jobs/recompute_scores.py` (write sub_score_history, read it for rolling mode, prune it)
- Modify: `src/bottlewatch/app/score/formula.py` (return raw_sub_scores in `ScoreResult.to_persisted`)
- Tests: `src/bottlewatch/tests/test_score_history_job.py`, `test_recompute_scores.py`

---

## 6. Workstream E: Update recompute job and settings

### 6.1 Changes

- Add to `src/bottlewatch/config.py`:
  - `geo_concentration_source: Literal["ontology", "universe_weighted"] = "universe_weighted"`
  - `score_normalization_mode: Literal["fixed", "rolling"] = "fixed"`
  - `score_bands_path: Path = Field(default=.../research/config/score_bands.json)`
- `recompute_scores.run()`:
  - Loads band config and logs version.
  - Loads sub-score history when `mode="rolling"`.
  - Branches HHI source on `settings.geo_concentration_source`.
  - Passes raw values through to `compute_segment_score`.
- `_LOOKBACK_DAYS` raised from 730 to **1825** (5 years) so that rolling bands have enough signal history for extractors that depend on `signals` (YoY, etc.).

### 6.2 Files to touch

- `src/bottlewatch/config.py`
- `src/bottlewatch/jobs/recompute_scores.py`

---

## 7. Workstream F: Frontend/API adjustments

### 7.1 Changes

- API `SegmentDetail` already exposes `sub_scores` with provenance. Add the raw value and normalization mode when available:
  - Extend `_sub_scores_to_api` to include `raw_value` and `normalization_mode` from `scores.raw_sub_scores` and `scores.normalization_mode`.
- Segment detail page: show `raw_value` in a tooltip or collapsible panel so users can see the metric behind the normalized score.
- Scoreboard: keep the existing `static_seed_share` warning; no new UI required for Phase 2 unless time permits a "rolling vs fixed" toggle.

### 7.2 Files to touch

- `src/bottlewatch/app/api/services.py`
- `src/bottlewatch/app/api/segments.py` (schema if needed)
- `frontend/app/segment/[slug]/page.tsx`
- Tests: frontend/TS tests as needed

---

## 8. Out of scope (deferred to follow-up)

These are part of the broader Phase 2 vision but are intentionally excluded from this implementation batch to keep the change set reviewable:

- **Point-in-time gating** using `ingested_at`/`released_at` for historical recomputes (requires ingest adapters to expose release dates).
- **EIA ISO/RTO data** for real `capacity_tightness` in power/data-center segments (requires new ingest adapter + data source).
- **Removing cross-segment macro proxies** (PPI/INDPRO/TCU) where they pretend to be segment-specific signals — this is a data-coverage decision that should happen after primary sources land.

---

## 9. Test plan

- **Unit:** `test_score_geo.py` — mock universe CSV and override file; assert HHI values, floor behavior, parent grouping, seed fallback on divergence, unknown-region drop.
- **Unit:** `test_score_normalize.py` — fixed-band mapping, rolling-band mapping, winsorization, flat/short history fallback, `None` imputation, seed passthrough.
- **Unit:** `test_score_extractors.py` — raw values and source keys for every extractor; no inline clamping.
- **Integration:** `test_score_formula.py` — raw input → normalized output → final score; imputation flagged; seed divergence fallback for geo.
- **Integration:** `test_recompute_scores.py` — full run with `universe_weighted` HHI and `fixed` normalization; then one run with `rolling` normalization using backfilled sub-score history.
- **Migration:** `make check-migrations` clean after `0007`.
- **E2E:** `bottlewatch-recompute --backfill-since 2024-01-01` populates `sub_score_history` without crashing.

---

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Replacing HHI changes scores materially | Keep seed fallback when divergence > 0.30; ship with `geo_concentration_source=universe_weighted` only after tests pass. |
| Rolling mode produces unstable scores with short history | Default to `fixed`; `rolling` auto-falls back to fixed when history < 2 years. |
| Extractor refactor breaks many tests | Update tests in the same PR; run `make test` before merge. |
| 5-year lookback slows signal query | Index on `(segment, signal_name, observed_at)` already exists; the query returns point-in-time rows for recompute, not all history. |
| Sub_score_history table grows large | Same 1000-day retention as score_history; prune each run. |

---

## 11. Definition of done

- `make test`, `make check-migrations`, `ruff check`, `ruff format --check`, and `pyright` all pass.
- `bottlewatch-recompute` runs successfully with `GEO_CONCENTRATION_SOURCE=universe_weighted` and `SCORE_NORMALIZATION_MODE=fixed`.
- A backfill since 2024-01-01 populates `sub_score_history`.
- `research/04_scoring_methodology.md` is updated to describe universe-weighted HHI and the normalization pipeline.
- This plan is closed and a follow-up plan is written for the deferred items (point-in-time gating, EIA ISO/RTO, proxy removal).
