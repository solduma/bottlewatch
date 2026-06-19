# Spec: T1.4 — Honest backtest inference

**Date:** 2026-06-18
**Covers:** T1.4 from `2026-06-18-improvement-assessment.md`.
**Why spec-first:** money-/methodology-sensitive; the headline IC and its
"significance" are the product's validation claim. Per CLAUDE.md SDD.

---

## Problem (verified against the code)

The backtest reports IC point estimates with p-values and bootstrap CIs that
rest on **inconsistent and over-confident** statistical assumptions:

1. **Point estimate, CI, and p-value come from three different estimators.**
   In `segment_ic_with_ci` (`stats.py:144-156`): `rho` is a pooled
   `spearmanr(xs, ys)` over every (ticker, date) tuple; `p_value` is scipy's
   **asymptotic** Spearman p (assumes i.i.d.); `ci_low/ci_high` come from
   `_block_bootstrap_ic`. Three methods, one row — they can disagree (a CI that
   excludes 0 while p > 0.10, or vice-versa).

2. **Pooled Spearman treats correlated observations as independent.** Both the
   per-segment `rho` and the headline `overall_ic` (`backtest.py:386-388`,
   `_compute_ic`) pool ~200 tickers × monthly dates into one `spearmanr`. Tickers
   within a segment co-move and dates overlap, so the effective sample size is
   far below `n`. The asymptotic p-value (≈ n-driven) is therefore **far too
   small** — pseudo-replication. The headline number is the most over-powered.

3. **Forward windows overlap → autocorrelated observations.** Eval dates step 30
   days (`_eval_dates`, `step_days=30`) but the default forward window is 90 days
   (`backtest.py:463`). Consecutive eval points share ~⅔ of their return path.
   `_block_bootstrap_ic` nods at this with `block_size=3` (`stats.py:47`) but the
   block size is hard-coded and unrelated to the 90/30 = 3 overlap ratio, and the
   pooled p-value ignores it entirely.

4. **No multiple-comparison control on the headline IC.** Per-segment ICs get
   Benjamini-Hochberg (`backtest.py:365`), but `overall_ic`/`overall_p_value` do
   not — yet the headline is the most-quoted figure.

5. **Constant-score selection effect is logged but not disclosed in the report.**
   Static-seed segments (no time-varying B) are dropped from IC
   (`backtest.py:339-357`); a WARNING fires but the `BacktestReport` doesn't carry
   the count, so a reader of the JSON/UI sees an IC computed only on the subset
   that had live data, with no in-band caveat.

---

## Design

**Core principle: the date-level block bootstrap is the single source of truth
for the point estimate, the CI, *and* the p-value.** One estimator, internally
consistent. Drop the asymptotic scipy p-value from the inference path.

### Inputs → outputs

- **Per-eval-date IC.** For each eval date `t`, compute one cross-sectional
  Spearman IC over that date's (B, forward_return) pairs (needs ≥4 points and
  variance, else the date is skipped). This collapses the pseudo-replication:
  the unit of observation becomes the *date IC*, not the (ticker, date) tuple.
- **Point estimate** = mean of the per-date ICs (equivalently the bootstrap
  mean; report the mean of per-date ICs as `rho`).
- **CI** = 2.5/97.5 percentiles of a block bootstrap that resamples **per-date
  ICs** in contiguous blocks (preserves the forward-window overlap).
- **p-value** = bootstrap two-sided p for H0: mean IC = 0, computed as
  `2 * min(share of bootstrap means ≤ 0, share ≥ 0)`, floored at `1/n_bootstraps`.
- **`block_size`** = `ceil(forward_days / step_days)` (default 90/30 = 3) instead
  of a hard-coded literal, threaded from the caller. Document the derivation.
- **Headline (`overall_ic`)**: same date-level method pooled across all segments
  (one cross-sectional IC per date over all segments' points), with its own
  bootstrap p-value and CI. Add `overall_ci_low`/`overall_ci_high` to the report.
- **BH** runs on the new bootstrap per-segment p-values (consistent estimator).
- **Disclosure**: add `n_constant_score_segments: int` and
  `n_segments_evaluated: int` to `BacktestReport` so the selection effect is
  in-band, not just a log line.

### Behavioral contract

- A segment/headline with < 2 usable eval dates → `rho=None`, `p_value=None`,
  `ci=None` (cannot bootstrap a distribution of dates). Today's `< 4 points`
  degenerate guard is preserved at the per-date level.
- Reported `rho` for a real result = mean of per-date ICs; the CI brackets it by
  construction (both from the same bootstrap distribution), fixing the
  estimator-mismatch in (1).
- p-values are bootstrap-derived; they will be **larger** (more honest) than
  today's asymptotic ones. Significance flags will tighten — expected, not a bug.
- Determinism preserved: bootstrap `seed=42` unchanged.

### Error modes

- Empty eval set / all dates degenerate → `BootstrapResult` with `None`s and the
  report's IC fields None (matches existing empty-report path `backtest.py:228`).
- p-value floor `1/n_bootstraps` avoids reporting a literally-zero p.

### Does NOT

- Change basket construction, forward-return logic, or the point-in-time score
  gating (those are separate items — see the universe-leak note below).
- Change `step_days`/`forward_days` defaults or the scoring pipeline.
- Re-architect `_run_single_mode` (the 200-line function) — out of scope; a
  follow-up. Only the inference functions change.

### Testable properties

1. **Consistency:** for any non-degenerate input, `ci_low ≤ rho ≤ ci_high`
   (point estimate inside its own CI) — impossible to violate once both derive
   from one bootstrap.
2. **Pseudo-replication fixed:** duplicating every ticker within each date (more
   correlated rows, same date structure) leaves the date-level IC, its CI width,
   and p-value ~unchanged — whereas today's pooled p-value would shrink. A direct
   regression test of the core flaw.
3. **block_size derivation:** `block_size == ceil(forward_days/step_days)`.
4. **p-value sanity:** a synthetic perfectly-monotonic B↔return relationship →
   small bootstrap p and CI excluding 0; pure noise → p near 1 and CI spanning 0.
5. **Disclosure:** a run with K static-seed segments reports
   `n_constant_score_segments == K` and `n_segments_evaluated == total − K`.
6. **Determinism:** identical inputs + seed → identical CI/p across runs.

---

## Critical review (one pass, per CLAUDE.md SDD)

- **Will date-level ICs leave enough sample?** The Phase-3 run had ~10 eval dates
  (`2026-06-14-phase3-executive-summary.md`). A bootstrap over 10 date-ICs is
  thin — CIs will be wide. That is the *honest* answer (the old tight CIs were an
  artifact of pseudo-replication), but we must **not** present a 10-date bootstrap
  as precise. Mitigation: report `n_eval_dates` alongside every IC (already in the
  report) and treat < ~8 dates as low-confidence in the UI copy. Surfacing the
  width honestly is the point of the ticket.
- **Simpler alternative considered — keep pooled rho, only swap the p-value for a
  bootstrap p.** Rejected: it fixes (1)/(2)'s p-value but leaves `rho` a pooled
  statistic whose CI (date-level) wouldn't bracket it cleanly, re-introducing the
  estimator mismatch. One estimator end-to-end is cleaner and more defensible.
- **Alternative — Newey-West / HAC SE on pooled rho.** Rejected for now: heavier,
  needs a lag choice as arbitrary as block_size, and is harder to unit-test than a
  transparent block bootstrap. The bootstrap is already in the codebase.
- **Out-of-scope risk worth naming, not fixing here:** the assessment's other
  backtest finding — the **point-in-time universe leak** (mcap/exposure/membership
  read from today's CSV in `baskets.py:79-119`) — is *not* addressed by this spec.
  It biases *basket returns*, not the IC. Flag it as a separate ticket so this
  PR's scope stays "inference honesty," and the leak isn't silently assumed fixed.
- **Backward-compat / contract:** adding `overall_ci_low/high`,
  `n_constant_score_segments`, `n_segments_evaluated` to `BacktestReport` is
  additive — the API serializes via `to_jsonable()`/`asdict`, so the JSON gains
  fields. The TS `BacktestReport` (`api.ts:372`) and `/backtest` page must add the
  optional fields; no removals, so existing consumers don't break. Update the TS
  interface + render the new disclosure counts and overall CI in the UI.
- **Edge: does removing the asymptotic p-value break BH?** BH consumes whatever
  p-values it's given; feeding bootstrap p-values is a drop-in. The
  `bh_rejected` semantics are unchanged, just computed from honest p's.

---

## Implementation order (when approved)

1. `stats.py`: add a date-level bootstrap that returns mean IC + CI + bootstrap
   p in one `BootstrapResult` (extend the dataclass with `p_value`); derive
   `block_size` from forward/step. Rewrite `segment_ic_with_ci` to use it; drop
   the scipy p from the inference path (keep scipy only for the per-date IC).
2. `backtest.py`: compute the headline IC the same date-level way; thread
   `forward_days`/`step_days` into the bootstrap; populate the new report fields;
   keep the existing constant-score WARNING.
3. `basket_report.py`: extend `BacktestReport` (+ `overall_ci_low/high`,
   `n_constant_score_segments`, `n_segments_evaluated`).
4. Tests: the 6 properties above (new `test_backtest_stats.py` cases +
   `test_backtest.py` report-field assertions).
5. Frontend: extend the TS `BacktestReport`, render overall CI + the disclosure
   counts, and a low-confidence hint when `n_eval_dates` is small.
6. Regenerate the Phase-3 summary numbers? **No** — leave historical docs; note in
   the PR that headline p-values will rise under the new method.
```
