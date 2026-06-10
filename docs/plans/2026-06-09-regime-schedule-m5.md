# Plan: Regime gap fix + scheduled refresh verification + M5 extension

Date: 2026-06-09
Status: In plan mode — awaiting approval before implementation

---

## Background

The user asked for three things in order:

1. **Fix the regime threshold gap** — segments with B in [30, 70) and strongly negative momentum (B' < -15) currently fall through to STABLE instead of getting a RESOLVING label.
2. **Wire up scheduled refresh** — ensure `make schedule` works and the launchd agents run cleanly.
3. **Pull the M5 items** — extend the M5 pattern (dynamic sub-scores from signals) to the next sub-score/segment.

---

## Task 1: Fix the regime threshold gap (7th cell)

### Problem

The 6-cell regime table has a hole in the lower-right quadrant. Live data:

| Segment | B | B' | Current regime | Should be |
|---|---|---|---|---|
| power_generation_oem | 52.7 | -19.4 | STABLE (fallback) | RESOLVING |
| data_center_shell | 50.9 | -22.6 | STABLE (fallback) | RESOLVING |
| advanced_node_fabs | 69.3 | -2.1 | STABLE | STABLE (correct) |

**Trace for (52.7, -19.4):**
- PEAKING: B ≥ 70? ✗
- PEAKED: B ≥ 70? ✗
- RESOLVING: B ≥ 70? ✗
- EMERGING: B' ≥ +30? ✗
- STABLE: B' ≥ -15? B' = -19.4 < -15 → ✗
- RESOLVING_FROM_LOW: B < 30? B = 52.7 ≥ 30 → ✗
- **No cell matches → falls through to STABLE** (regime.py:153-160)

### Fix

Add a 7th cell to `research/06_regime_thresholds.json`:

```json
{"b_min": 30, "b_prime_max": -15, "b_max": 70, "regime": "RESOLVING"}
```

Place it **between EMERGING and STABLE** in the JSON `cells` array so the first-match ordering is correct:
1. PEAKING
2. PEAKED
3. RESOLVING (B ≥ 70, B' < 0)
4. EMERGING
5. **NEW: RESOLVING (30 ≤ B < 70, B' < -15)**
6. STABLE
7. RESOLVING_FROM_LOW

**Why "RESOLVING" and not a new label?** Two reasons:
- The hard guard (`screener.py:EXCLUDED_REGIMES_LONG`) already blocks RESOLVING from long baskets — this is the intended policy per methodology §7.8.
- The short basket (`screener.py:88`) filters by `r.regime == "RESOLVING"` — the new cell's segments should appear in the short basket (they're resolving). A new label would require updating the short-basket filter too.

### Files changed

- `research/06_regime_thresholds.json` — add 7th cell, bump version to "M2-v2"
- `src/bottlewatch/tests/test_score_regime.py` — update version pin, add boundary test for new cell, update cell-count assertion (now 7 JSON cells, still 6 unique regime names)
- `research/04_scoring_methodology.md` §7.6 — update the 6-cell table to 7-cell

### Post-fix

Run `bottlewatch-recompute` to update the live `scores` table. The two mis-classified segments will shift from STABLE → RESOLVING.

---

## Task 2: Wire up scheduled refresh

### Current state

`launchctl list | grep bottlewatch` shows:
```
47095	2	com.bottlewatch.refresh
-	0	com.bottlewatch.recompute
```

Both agents are **loaded**. The refresh agent has PID 47095 and status 2 (the last run exited with code 2, possibly from a SIGTERM/kill). The recompute agent shows status 0 (last run succeeded).

`which uv` → `/Library/Frameworks/Python.framework/Versions/3.11/bin/uv` — this **is** in the plist PATH. ✓

### Known issue: sec_insider log noise

The `data/cache/refresh.log` shows `mismatched tag` warnings from `sec_insider` (e.g., `malformed Form 4 XML, accession=0001333493-25-000080: mismatched tag: line 119, column 23`). These are `xml.etree.ElementTree.ParseError` exceptions caught at `sec_insider.py:457-463`.

These are **not** the semantic warnings we fixed earlier (holdings-only, derivative-only, etc.). They are structural XML parse errors — the filing's XML is genuinely malformed. Dozens of accessions from the same CIK (0001333493) show the same line/column pattern, suggesting a systematic issue with that filer's XML generator.

This is **expected EDGAR data quality edge case**, not a code bug. The current behavior (log warning + skip) is correct. The problem is log noise: the user sees "mostly malformed and skipped" and thinks the adapter is broken.

### Fix

Demote `ET.ParseError` from WARNING to DEBUG in `sec_insider.py:457-463`. Add a per-run summary at INFO level if >0 filings were skipped for this reason, so the operator knows it's happening without being flooded.

```python
# Current:
except ET.ParseError as exc:
    _LOGGER.warning("sec_insider: malformed Form 4 XML, accession=%s: %s", ...)

# Proposed:
except ET.ParseError as exc:
    _LOGGER.debug("sec_insider: unparseable XML (expected EDGAR edge case), accession=%s: %s", ...)
    # A run-level counter can be added to the adapter's fetch() method
    # and logged once at the end: "N filings skipped due to unparseable XML"
```

### Verification steps

1. Trigger a manual run: `launchctl start gui/$(id -u)/com.bottlewatch.refresh`
2. Tail the log: `tail -f data/cache/refresh.log`
3. Confirm: all adapters run, no ERROR status, sec_insider warnings are reduced

### Files changed

- `src/bottlewatch/app/ingest/sec_insider.py` — demote ET.ParseError log level, add run-level counter

---

## Task 3: Pull the M5 items — dynamic lead_time_growth for transformers_tnd

### Context

The README marks 3 M5 items complete:
- [x] Sparkline charts
- [x] FRED A35SNO for transformers_tnd.demand_signal
- [x] Ontology-derived HHI for geo_concentration

The next natural extension is **dynamic lead_time_growth** for `transformers_tnd`. Currently all 10 segments have static `lead_time_growth` from `scoring_seed.json`. The formula has override parameters only for `geo_concentration` and `demand_signal`; `lead_time_growth` has no override path.

### Approach

Use the **existing FRED WPU1321 signal** (transformer PPI) as a proxy for lead_time_growth. The PPI absolute level correlates with lead times — high PPI means tight market means long lead times.

**Why reuse WPU1321?** We already ingest it for `capacity_tightness`. Using the same raw signal for two sub-scores is acceptable because:
- `capacity_tightness` uses YoY growth (dynamic tightness proxy)
- `lead_time_growth` will use the absolute level (normalized over a 5-year band conceptually; in M5 we map to [0, 1] with a historical band)
- The formula treats them as separate dimensions with different weights

This follows the exact same pattern as the existing `demand_signal` and `geo_concentration` overrides:
1. Add `lead_time_growth(segment, signals)` dispatch in `extractors.py`
2. Add `_transformer_lead_time_growth(signals)` using the WPU1321 absolute level
3. Add `lead_time_growth: float | None = None` parameter to `compute_segment_score()` in `formula.py`
4. Add `_compute_lead_time_by_segment()` in `recompute_scores.py`, wire it through
5. Add tests for the extractor, the override in formula, and the end-to-end in recompute

### Files changed

- `src/bottlewatch/app/score/extractors.py` — add `lead_time_growth()` dispatch + `_transformer_lead_time_growth()`
- `src/bottlewatch/app/score/formula.py` — add `lead_time_growth` parameter and override logic
- `src/bottlewatch/jobs/recompute_scores.py` — add `_compute_lead_time_by_segment()` and pass to `compute_segment_score()`
- `src/bottlewatch/tests/test_score_extractors.py` — add extractor tests
- `src/bottlewatch/tests/test_score_formula.py` — add override tests
- `src/bottlewatch/tests/test_recompute_scores.py` — add end-to-end tests

### Alternative considered

Instead of absolute PPI level, we could map YoY growth to lead_time_growth using a different band than capacity_tightness. But this would make the two sub-scores perfectly correlated (same raw signal, different mapping), which reduces score diversity. The absolute level approach is better because PPI level and PPI YoY are different signals.

However, the absolute level mapping requires defining a historical min/max band, which we don't have 5 years of data for. In practice we'd use a hardcoded band based on FRED's historical range (e.g., 80-150 index points) and map to [0, 1]. This is a reasonable M5 approximation.

**Decision:** Proceed with absolute level mapping using a conservative band (WPU1321 range [80, 150] → [0, 1]). Document the approximation in the methodology.

---

## Implementation order

1. **Task 1** (regime gap) — smallest change, highest user-facing impact. The mis-classified segments are visible on the dashboard today.
2. **Task 2** (scheduled refresh) — verify/fix in parallel while running recompute for task 1.
3. **Task 3** (M5 extension) — largest change, lowest urgency. Do after tasks 1+2 are verified.

---

## Testing strategy

- Unit tests for each changed module (regime, sec_insider, extractors, formula, recompute)
- `make test` must pass (ruff + pytest)
- Manual verification: `bottlewatch-recompute` → check live scoreboard shows correct regimes
- Manual verification: `launchctl start` → check refresh.log for clean run

## Rollback

- Task 1: revert JSON edit + restore version "M2-v1" + re-run recompute
- Task 2: revert log-level change in sec_insider.py
- Task 3: revert parameter additions in formula.py and recompute_scores.py (extractor can stay — unused until wired)
