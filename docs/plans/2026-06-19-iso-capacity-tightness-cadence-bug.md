# Ticket: `_iso_capacity_tightness` returns None on real ISO/RTO data

**Date filed:** 2026-06-19
**Severity:** medium — silent loss of the ISO/RTO capacity-tightness signal
**Scope:** PRE-SESSION code (commit `c8acc72`, "phase 4 scoring calibration,
ISO/RTO integration"). Surfaced by the 2026-06-19 code review of PR #1 but
NOT introduced by that PR's session work — filed separately rather than fixed
inline to keep the PR scoped.

---

## Symptom

`_iso_capacity_tightness` (`src/bottlewatch/app/score/extractors.py`) returns
`None` on realistic ISO/RTO data, so capacity_tightness silently falls back to
`_power_tightness`/imputed and the ISO/RTO integration contributes no signal.

## Root cause (verified)

The function groups signals by `(region, observed_at)`, picks the **single
latest `observed_at` per region**, and then requires **both** `iso_peak_load_mw`
**and** `iso_capacity_mw` at that one date:

```python
latest_by_region[region] = max(d for that region)
vals = by_region_month[(region, latest_d)]
cap, peak = vals.get("iso_capacity_mw"), vals.get("iso_peak_load_mw")
if cap is not None and cap > 0 and peak is not None:
    ratios.append(min(peak / cap, 1.0))
```

But the EIA ISO/RTO ingest (`src/bottlewatch/app/ingest/eia_isorto.py`) emits the
two signals on **different periods**:
- `iso_peak_load_mw`: one row per month across the (recent) fetch window, dated
  `date(year, month, 1)`.
- `iso_capacity_mw`: pinned to `_latest_capacity_month(today)`, which subtracts
  ~3 months (a publication lag).

So for every region the latest `observed_at` is the most-recent **peak** month,
whose `vals` dict contains only `iso_peak_load_mw`. `cap` is `None`, the region
is skipped, `ratios` ends up empty, and the function returns `None` — on every
real run, not just edge cases.

## Why tests didn't catch it

Existing unit tests construct fixtures where peak and capacity share the same
`observed_at`, so the latest-date dict has both signals. Real ingest never
produces that alignment.

## Proposed fix (design only — not implemented here)

Decouple the two signals' "latest" selection instead of requiring a shared date:
- Take the latest `iso_peak_load_mw` per region AND the latest `iso_capacity_mw`
  per region independently, then form the ratio from those two most-recent
  values (capacity changes slowly, so a 3-month-older capacity is acceptable).
- Guard against using a capacity value that is implausibly stale relative to the
  peak (e.g. > 12 months apart → skip region), and log when a region is skipped.

## Testable properties for the fix

1. Peak (monthly) + capacity (3-month-lagged) on different `observed_at` per
   region → a non-None mean utilization is returned (the current bug case).
2. A region with peak but no capacity at all → skipped, not crashing; if no
   region has any capacity, return None.
3. Capacity newer-than-peak and peak newer-than-capacity both handled.
4. Utilization still clamped to 1.0 and averaged across regions.

## Related

- The publication-lag pattern here is the same shape as `eia_capacity.py`
  (`_PUBLICATION_LAG_MONTHS`); consider whether `eia_isorto` should share that
  abstraction — see review finding on per-adapter lag drift.
