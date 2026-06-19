# Spec: Fix momentum (B') to a true trailing-6-month median

**Date:** 2026-06-19
**Covers:** Tier-3 momentum mis-spec from `2026-06-18-improvement-assessment.md`.
**Why spec-first:** B' drives regime classification (EMERGING/PEAKING/RESOLVING)
and the long/short baskets — money-sensitive scoring. Per CLAUDE.md SDD.

---

## Problem (verified against code + methodology)

`_momentum` (`src/bottlewatch/app/score/formula.py`) computes
`B' = 100 * (B_now − B_then) / B_then` where `B_then` should be "B as of 6
months ago." The methodology (`research/04_scoring_methodology.md` §7.5, lines
668–672) is explicit:

> We use the 6-month **median** of B (rather than the end-point value) as
> B(t-6mo) to suppress noise — this matters for segments with high
> month-to-month volatility (e.g. cooling_water has 30-day summer seasonality).

So `B_then` is meant to be the **median of all B values over the trailing
6-month window** (now-180d → now), smoothing volatility.

The implementation does something different (`formula.py`):

```python
target = now - timedelta(days=180)
window = [v for ts, v in history if abs((ts - target).total_seconds()) <= 15 * 86_400]
```

It takes a **±15-day point sample centered on t-6mo** — the median of the 1–3
points that happen to land near the 180-day mark, NOT a trailing-6-month median.
Consequences:
- **Defeats noise suppression.** The whole point (per the methodology) is to
  smooth a volatile series; a 30-day point sample at one instant doesn't.
- **Cadence-fragile.** The recompute loads ~7 months of history
  (`recompute_scores.py:428`, `cutoff = until - 210 days`) and runs monthly, so
  the ±15-day window typically contains exactly ONE point → the "median" is a
  no-op and B' swings on a single historical row. A gap in runs or a backfill
  landing off the 180-day grid silently collapses the window to empty → B' = 0.
- The comment says "30-day window" but the docstring says "6-month median" —
  the two disagree, and neither matches the methodology's trailing-6-month median.

## Design

Make `B_then` the **median of B over the trailing 6 months** [now-180d, now],
matching the methodology. Keep everything else (the formula, the ±100 cap, the
`B_then < 5 → +100` convention, the empty-history → 0.0 first-compute case).

### Inputs → outputs
- `history`: list of `(computed_at, B)` over (at least) the trailing 6 months,
  as already passed by the recompute job.
- `window = [v for ts, v in history if now-180d <= ts <= now]` — the full
  trailing-6-month set, not a point sample. (Exclude the current point if it is
  in `history`; the recompute passes prior history only, but guard with `ts < now`
  to be safe so B_now isn't double-counted into its own baseline.)
- `B_then = median(window)`.
- If `window` is empty (genuinely no history in the trailing 6 months) →
  return 0.0 (first-compute / cold-start, unchanged semantics).

### Behavioral contract
- A segment with a flat B history → B_then ≈ B_now → B' ≈ 0 (STABLE). Unchanged.
- A volatile segment → B_then is the smoothed 6-month median, so a single
  outlier month no longer whipsaws B' (the methodology's intent).
- `B_then < 5` → B' = +100 (named constant, unchanged convention).
- `B_now is None` → None; empty trailing window → 0.0.
- Cap stays [-100, +100].
- **Monthly cadence now works as intended:** ~6 monthly points feed the median
  instead of 1 point near t-6mo.

### Edge cases / error modes
- History with only points OLDER than 6 months (e.g. a long gap) → trailing
  window empty → 0.0. Acceptable: we have no recent baseline to compare against,
  same as cold-start. (Document it; do not invent a baseline.)
- Even vs odd window length → standard median (mean of two middles for even).
- Does NOT extrapolate or interpolate missing months.

### Does NOT
- Change the B' formula, the ±100 cap, the `<5 → +100` rule, the regime
  thresholds, or the recompute's 7-month history load (7mo ⊇ 6mo, fine).
- Add the `B'_capped_at_100` flag the methodology mentions (separate, not in
  scope — the cap already applies; surfacing the flag is future work).
- Touch the `recompute_scores` history window (already loads ≥6 months).

### Testable properties
1. **Trailing median, not point sample:** history with monthly points across 6
   months → B_then equals the median of all of them (not just the one near
   t-6mo). A test that today's code fails: give 6 monthly points where the value
   near t-6mo is an outlier vs the median — assert B' uses the median.
2. **Noise suppression:** a single outlier month inside the window moves B' less
   than it would under an end-point/point-sample baseline.
3. **Monthly cadence robustness:** exactly one point per month for 6 months →
   non-degenerate median (today this collapses to 1 point).
4. **Cold start:** empty history → 0.0; history entirely older than 6 months →
   0.0.
5. **Conventions preserved:** B_then < 5 → +100; flat history → ~0; cap at ±100.
6. **Pure + isolated:** `_momentum` (or an extracted `_median_b_trailing`) is
   unit-tested directly, not only through the 13-arg `compute_segment_score`.

---

## Critical review (one pass, per CLAUDE.md SDD)

- **Does this change live scores / regimes?** Yes — that's the point, and it's
  money-sensitive. Today most segments have ≤7 months of monthly history, so the
  ±15-day window usually holds 1 point and B' is effectively an end-point delta.
  Switching to the trailing median will change B' for any segment whose 6-month
  B path isn't flat, which can flip EMERGING/PEAKING/RESOLVING cells. Mitigation:
  (a) the change makes B' MATCH the documented methodology (it's a correctness
  fix, not a new policy); (b) **verify empirically** before merge by recomputing
  and diffing the regime distribution vs current, and surface the count of
  segments whose regime changes rather than shipping silently. If the diff is
  large/surprising, report it for a human call.
- **Should the current point also be in the median window?** No — B_then is the
  *baseline* 6 months ago; including B_now would bias the baseline toward the
  present and shrink B'. The recompute passes prior history (not the current
  row), but the `ts < now` guard makes this robust regardless of caller.
- **Window definition: trailing [now-180d, now] vs [now-180d ± something]?** The
  methodology says "6-month median of B" to suppress noise → the natural reading
  is the trailing 6-month window. Using the *full* trailing window (not a band
  around t-6mo) is what actually smooths. Chose trailing-window median.
- **Simpler alternative — keep the point sample but widen the band to ±90d.**
  Rejected: still a band around t-6mo, not a trailing median; arbitrary width;
  doesn't match the methodology text. The trailing-window median is both simpler
  and spec-faithful.
- **Naming/extraction:** extract the median-baseline into a small pure helper so
  property tests hit it directly (the assessment flagged the lack of a narrow
  seam). Promote `5.0` and `180` to named constants
  (`_MOMENTUM_NEAR_ZERO_B`, `_MOMENTUM_WINDOW_DAYS`).
- **Backfill point-in-time interaction:** the as-of recompute already gates
  history by `computed_at <= upper`; the trailing-median reads only that gated
  history, so no new look-ahead. (Unchanged from today.)

---

## Implementation order (when approved)

1. `formula.py`: rewrite `_momentum` to take the trailing-6-month median; add
   `_MOMENTUM_WINDOW_DAYS = 180` and `_MOMENTUM_NEAR_ZERO_B = 5.0`; fix the
   stale "30-day window"/docstring wording to match. Keep cap + conventions.
2. Tests: the 6 properties in `test_score_formula.py` (extend; add direct unit
   tests on the momentum baseline — the current suite only has
   `test_momentum_zero_on_first_compute`).
3. **Empirical check (gate before merge):** run `bottlewatch-recompute` on a DB
   with ≥6 months of history (or a synthetic fixture) and report how many
   (segment, horizon) regimes change vs the old code. Include the count in the
   PR body. No silent regime churn.
4. No frontend change (B' is already surfaced); no methodology-doc change (this
   makes code match the doc).
