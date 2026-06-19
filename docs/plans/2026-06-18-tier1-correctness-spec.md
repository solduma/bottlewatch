# Spec: Tier-1 Correctness Fixes (released_at + NO_DATA gate)

**Date:** 2026-06-18
**Covers:** T1.1 and T1.2 from `2026-06-18-improvement-assessment.md`.
Both are spec-required (point-in-time data + scoring methodology, money-sensitive).

---

## T1.1 — Populate `released_at`

**Problem:** `signals.released_at` (DB, `models.py:78`) is never written, so the
point-in-time gate `coalesce(released_at, ingested_at)` (`recompute_scores.py:224`)
always falls back to `ingested_at` → look-ahead bias in backtests.

**Inputs → outputs:**
- Add `released_at: datetime | None = None` to `RawSignal` (`base.py:51`).
- `_write_signals` (`refresh_daily.py:223`) passes `s.released_at` into `Signal(...)`.
- Adapters that already model publication lag set it from a `date` (coerced to a
  naive-UTC `datetime` at midnight, matching the table's naive-UTC convention):
  - `epa_egrid`: `EGRID_PUBLICATION_DATE` / `WRI_PUBLICATION_DATE` (already constants).
  - `eia_860m`: the release month it walks back to (`_latest_release_month`).
  - `eia_capacity`: the release month from `_latest_month_window`.

**Behavioral contract:**
- `released_at` is the date the source *published* the value, never after the run.
- Adapters with no known lag leave it `None` → gate still coalesces to
  `ingested_at` (today's behavior, unchanged). **No regression for unmodified adapters.**
- For the three adapters above, a backfilled recompute now gates on the true
  release date, not fetch time.

**Error modes:** a release date in the future relative to `observed_at` is a bug;
not asserted in v1 (the three sources all have release ≥ observed by construction).

**Does NOT:** change the gate logic, add `released_at` to FRED/Comtrade/SEC/price
adapters (separate follow-up), or backfill historical NULLs.

**Testable properties:**
1. A `RawSignal` with `released_at` set persists that value through `_write_signals`.
2. `epa_egrid`/`eia_860m`/`eia_capacity` emit signals with non-null `released_at`
   equal to their publication date.
3. Adapters left unmodified still emit `released_at=None`.

---

## T1.2 — Re-enable the NO_DATA gate

**Problem:** `data_completeness` (`formula.py:261`) counts `v is not None`, but
`normalize_subscore` always returns a float (imputes 0.5, `imputed=True`). So
completeness ≡ 1.0, the gate (`regime.py:193`, `no_data_threshold=0.4`) is dead,
and fully-imputed segments report confident B≈50 STABLE.

**Inputs → outputs:**
- Compute completeness from **provenance weight**, not None-ness:
  `data_completeness = 1 - Σ w_i over sub-scores where provenance[i].imputed`.
  Uses `_WEIGHTS[horizon]` (already in scope at `formula.py:266`).
- `classify(score, momentum, data_completeness)` is unchanged — it already returns
  NO_DATA when `completeness < NO_DATA_THRESHOLD` (0.4).

**Behavioral contract:**
- A segment whose imputed sub-scores carry > 0.6 of the weight (completeness < 0.4)
  → regime `NO_DATA`.
- `score`/`momentum` remain the computed values (NOT nulled) so the UI can still
  show B; the regime label is the trust signal. *(Decision: see critical review.)*
- A segment with all real (non-imputed) sub-scores → completeness 1.0, unchanged.

**Error modes:** none new; completeness stays in [0, 1] (sum of a weight subset).

**Does NOT:** change weights, the 0.4 threshold, or null out score/momentum.

**Testable properties:**
1. All-imputed segment → `data_completeness == 0.0` and `regime == NO_DATA`.
2. All-real segment → `data_completeness == 1.0`, regime from the 6-cell table.
3. Partial: imputing exactly the lowest-weight sub-score keeps completeness ≥ 0.4
   (still classified); imputing a majority of weight crosses to NO_DATA.
4. `ScoreResult.data_completeness` equals `1 - imputed_weight` (direct unit test).

---

## Critical review (one pass, per CLAUDE.md SDD)

- **Edge: does fixing completeness silently flip many live segments to NO_DATA?**
  Risk is real — if most segments rely on seed/imputed sub-scores today, the
  dashboard could go dark. Mitigation: the fix distinguishes `source=="seed"`
  (curated, `imputed=False`) from `source=="imputed"` (`imputed=True`). Seeds are
  NOT imputed, so seed-heavy segments keep completeness 1.0. Only genuinely
  *missing* (0.5-substituted) inputs reduce it. **Verify empirically** by running
  recompute and counting NO_DATA rows before merging — if the count is surprising,
  surface it rather than ship silently.
- **Edge: should NO_DATA null the score?** The `ScoreResult` docstring claims
  score/momentum are None for NO_DATA, but no code enforces it and the UI/history
  expect a number. Nulling is a larger, riskier change (history schema, frontend
  null-handling). Decision: **keep score populated, regime=NO_DATA**, and fix the
  stale docstring instead. Smaller, matches existing persistence.
- **Simpler alternative considered:** gate on `static_seed_share` instead of a new
  completeness formula. Rejected — seeds are *curated* values (legitimately
  confident), not missing data; conflating them would wrongly hide good segments.
- **released_at scope:** populating only 3 adapters is intentional minimum. The
  coalesce fallback means partial population is strictly better than none and
  carries no regression for the untouched adapters.

## Implementation finding (2026-06-18)

Empirically verified across all 64 segments × 3 horizons after the fix:
completeness now varies (0.65 / 0.80 / 0.90) instead of a constant 1.0, and
**zero** segments flip to NO_DATA — the safe outcome (no dashboard blackout).

Discovered while testing: in the **live config NO_DATA is structurally
unreachable** through `compute_segment_score`, because every segment has a
mandatory full seed entry (`research_values.for_segment` raises `KeyError`
otherwise) and seed values are never imputed. The only imputable production
sub-score is `capacity_tightness` (weight 0.35), so completeness floors at 0.65,
above the 0.4 threshold. The fix still matters: completeness now *reflects*
imputation truthfully and the gate is correctly wired (proven by a test that
injects a seed with `None` research values → all five imputed → completeness 0.0
→ NO_DATA). Making NO_DATA reachable for real would require optional seed
entries — a separate, larger change, deliberately out of scope here.
