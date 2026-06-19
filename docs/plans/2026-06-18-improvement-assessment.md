# Bottlewatch Improvement Assessment & Plan

**Date:** 2026-06-18
**Branch:** phase-4-calibration-isorto
**Scope:** Substance review (methodology soundness, data correctness, robustness) —
*not* hygiene. Gates, coverage (85%), and structure are already healthy.

Method: four parallel code reviews (scoring, ingestion, backtest/LLM,
frontend/API). The five highest-impact findings were verified directly against
the code before inclusion here (marked ✔ verified). Findings are tiered by
impact, not by effort.

---

## Tier 1 — Correctness (do first)

These quietly undermine the product's *edge*. Each is verified and well-localized.

### T1.1 — Look-ahead bias is structurally unpreventable (`released_at` never populated) ✔

- `signals.released_at` exists in the DB (`app/db/models.py:78`) but `RawSignal`
  (`app/ingest/base.py`) has **no such field**, and `_write_signals`
  (`jobs/refresh_daily.py:231`) never sets it → it is **always NULL**.
- Adapters already *compute* publication lag and then discard it:
  `eia_860m.py:78` (walks back ~2mo), `eia_capacity.py:73` (~3mo),
  `epa_egrid.py:213` (hard-coded `EGRID_PUBLICATION_DATE`/`WRI_PUBLICATION_DATE`).
- **Consequence:** any backtest joining on `observed_at` "sees" data months
  before it was published. The 2–3mo lags the adapters model are exactly the
  magnitude of look-ahead that inflates a walk-forward IC. The Phase-3 summary
  already admits this (`docs/plans/2026-06-14-phase3-executive-summary.md:37`:
  "Only `ingested_at` is used as the point-in-time proxy… can still leak").

**Fix:** add `released_at: datetime | None` to `RawSignal`; populate it in each
adapter from the lag it already knows; thread it through `_write_signals`. Then
the point-in-time recompute/backtest can gate on `coalesce(released_at,
ingested_at)` (the gate logic already coalesces — it just always gets NULL today).

### T1.2 — The NO_DATA regime is dead code ✔

- `data_completeness` (`app/score/formula.py:261`) counts `v is not None`, but
  `normalize_subscore` **always returns a float** — it imputes `0.5` for missing
  inputs and flags `imputed=True` (`app/score/normalize.py:215`).
- So `completeness == 1.0` always, the `NO_DATA_THRESHOLD` gate (`regime.py:193`)
  is unreachable, and a **fully-imputed segment surfaces as a confident B≈50
  STABLE score** with no "no data" badge. The provenance carries `imputed` per
  sub-score but no aggregate gate consumes it.

**Fix:** compute completeness from provenance (fraction of *non-imputed* weight),
not the always-true `v is not None`. Drive NO_DATA / `score=None` when imputed
weight exceeds a named, tested threshold.

### T1.3 — Frontend crash on null `exposure_pct` ✔

- API returns `exposure_pct: float | None` (`app/api/tickers.py:46`); TS declares
  non-nullable `number` (`frontend/app/lib/api.ts:84`) and dereferences
  `t.exposure_pct.toFixed(0)` (`tickers/page.tsx:479`) plus
  `a.exposure_pct - b.exposure_pct` (`TickersTable.tsx:28,87`).
- A ticker with an unparseable exposure cell — emitted as `null` **by design** —
  white-screens the page. Invisible to the type checker because the TS type lies.

**Fix:** change TS type to `number | null`; guard the three render/sort sites.

### T1.4 — Backtest inference overstates significance

- Bootstrap CI bounds a *pooled* Spearman treating every (ticker × date) tuple as
  independent (`app/backtest/stats.py:147`) → understates variance, CIs too tight.
- Headline pooled IC (`backtest.py:386`) gets **no** multiple-comparison control
  (per-segment ICs do, via BH at `:365`), and is the most over-powered number.
- 90-day forward windows stepped every 30 days (`backtest.py:182,463`) →
  heavily autocorrelated observations; `block_size=3` is hard-coded, unrelated to
  the 90/30 overlap.
- Constant-score (static-seed) segments are silently dropped (`backtest.py:339`),
  so the IC measures only the subset that had live data — a selection effect not
  disclosed in the headline.

**Fix (design, not yet scheduled):** make the block bootstrap the single source of
both point estimate and CI; resample at the *date* level (one IC per eval date),
drop the i.i.d. scipy p-value feeding BH, and disclose the constant-score
exclusion in the report.

---

## Tier 2 — Stale / misleading

### T2.1 — `anthropic` dependency is a lie ✔

- `anthropic>=0.49` (`pyproject.toml:25`, comment "daily research reasoning
  (Claude API)") is **imported nowhere in `src/`**. The actual LLM path is
  **Ollama** (`jobs/research_daily.py`, default model `llama3.2`,
  `config.py:48–53`). The "Ollama fallback" framing is backwards — Ollama is the
  only path.
- **Decision needed:** either remove the dep + fix the comment, or wire Claude in
  as the real reasoner (materially stronger than `llama3.2` for this task). This
  is a deliberate choice, not drift to leave unresolved.

### T2.2 — LLM output flows unvalidated into the DB

- Model text is persisted verbatim as `rationale_md` (`research_daily.py:373→474`).
  Nothing checks that cited signal names/numbers exist in `context.signals`; a
  hallucinated figure becomes an official "research rationale."
- LLM failures silently downgrade to `machine` rationale (`:381`), indistinguishable
  from "nothing was interesting" — operator can't tell an outage from a quiet day.

**Fix:** cheap post-hoc check that cited values appear in context; distinguish
"machine (not interesting)" from "machine (LLM errored)" in run counts.

### T2.3 — Silent-swallow adapters

- `fred.py:118` and `comtrade.py:67` use `except Exception: continue` with **no
  logging** — a renamed series ID degrades the signal to zero rows and the run
  still reports `OK`. `eia.py:196` does the opposite (one bad series kills all).
- Low test coverage (epa_egrid 71%, sec_edgar 74%, sec_insider 79%) lines up
  precisely with the **silent-fallback branches** — the riskiest coverage profile.

**Fix:** log-and-continue (EIA dialect) in fred/comtrade; per-series fault
tolerance in eia.py; orchestrator-level "OK with 0 rows but expected non-empty"
alarm.

---

## Tier 3 — Tech debt (real, lower urgency)

- **Momentum mis-specified vs docstring** — a ±15-day point sample, not a
  trailing-6-month median; cadence-fragile (`formula.py:313`). Extract to a tested
  pure function.
- **Sector map triplicated** (backend + 2 frontend spots), already drifting;
  `tickers/page.tsx:156` literally says "we should get this from the API." Add
  `sector` to `TickerRow`, delete the hardcoded `valueChain` array.
- **Audit promise unmet** — normalizer carries `band_min/max`
  (`normalize.py:74`) but recompute writes hardcoded `None`
  (`recompute_scores.py:621`).
- **API N+1** in ticker detail (`tickers.py:247`); `/scores/history` &
  `/backtest/report` use `response_model=dict`, defeating validation and feeding
  TS type-drift.
- **No shared data-fetching abstraction** on the frontend — 4+ hand-rolled
  loading/error/cancelled blocks. `SegmentDetailPage` turns any API error into a
  404 (`segment/[slug]/page.tsx:104`).
- **Untested load-bearing logic:** ProseMirror→markdown serializer
  (`thesis/page.tsx:42`), `chainLayout.ts`, tickers filter/sort pipeline.
- **Duplication:** SEC adapter helpers (→ `sec_common.py`); two HHI-floor impls
  (`geo.py:122` vs `extractors.py:442`); `_PROJECT_ROOT parents[4]` in 4 files.
- **YoY extractors assume `values[-13]` is exactly 12mo prior** (`extractors.py:192`)
  with no date check — silently wrong on irregular cadence.

---

## Execution order

1. **(this PR)** T1.1 `released_at` plumbing + T1.2 NO_DATA gate — spec-first per
   CLAUDE.md (scoring + point-in-time = spec-required zone). Spec lives at
   `docs/plans/2026-06-18-tier1-correctness-spec.md`.
2. Quick safe wins: T1.3 (exposure null-guard), T2.1 (anthropic dep decision),
   T2.3 (adapter logging).
3. Larger design work: T1.4 (backtest inference), T2.2 (LLM validation), then
   Tier 3 as capacity allows.
