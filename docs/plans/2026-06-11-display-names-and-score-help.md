# Plan: Display names for segments + score/B threshold documentation

Date: 2026-06-11
Status: In plan mode — awaiting approval before implementation

---

## Background

The user reported three usability gaps in the dashboard:

1. **Snake-case slugs everywhere.** The scoreboard, quadrant,
   segment detail page, sparkline `aria-label`, and ticker list
   all show `transformers_tnd` / `systems_rack_scale` etc. —
   ugly variable names instead of human-readable segment
   titles like "Transformers & Switchgear (T&D)".

2. **"Score" is ambiguous.** The scoreboard's columns are
   labeled `near / med / long` (the time horizon), and the
   values underneath are the B scores (0-100). A reader
   scanning the table can't tell at a glance that "73.5"
   under "near" is a *score* — it could be a price, a lead
   time, anything.

3. **The B ≥ 70 binding threshold (and B ≥ 50 basket-eligible
   threshold) need a UI affordance** so an investor can tell
   at a glance what the numbers mean. The user originally
   said "B>60" but the methodology's M2 calibration
   documents B ≥ 70 as the actual binding threshold
   (per `research/06_regime_thresholds.json`); the user
   confirmed B ≥ 70 in the plan AskUserQuestion.

User-confirmed scope (from AskUserQuestion):
- Threshold: **B ≥ 70** (binding), **B ≥ 50** (basket-eligible)
- Where to show: **tooltip on the score column header** (no
  legend, no footer, no caption)

---

## Approach

### 1. Segment display names

Add a `slug → human_name` mapping in a new module
`src/bottlewatch/app/segments_meta.py`. Pattern mirrors
the existing `app/score/ontology_segments.py` module
(also a hardcoded dict mapping slugs to ontology classes).

```python
# app/segments_meta.py
_SEGMENT_NAMES: dict[str, str] = {
    "advanced_node_fabs": "Advanced-Node Fabs",
    "advanced_packaging": "Advanced Packaging (CoWoS / 2.5D / 3D)",
    "cooling_water": "Cooling & Water",
    "data_center_shell": "Data Center Shell (Colo + Hyperscaler Self-Build)",
    "gpu_asic_silicon": "GPU / ASIC Silicon",
    "hbm_memory": "HBM Memory",
    "networking_interconnect": "Networking & Interconnect",
    "power_generation_oem": "Power Generation OEM",
    "systems_rack_scale": "Systems OEM/ODM",
    "transformers_tnd": "Transformers & Switchgear (T&D)",
}

def display_name(slug: str) -> str:
    """Return the human-readable name for a segment slug, falling
    back to the slug itself when no mapping exists.
    """
    return _SEGMENT_NAMES.get(slug, slug)
```

The values match the `# Title` line in
`research/01_segments/<slug>.md` so the markdown remains the
canonical source; this dict is a one-time copy that the
operator maintains alongside the research artifacts
(same pattern as the ontology mapping).

### 2. Backend: API exposes the name

Add a `name: str` field to the `SegmentScore` and
`SegmentDetail` Pydantic models in
`src/bottlewatch/app/api/segments.py`. Populate it in
both list and detail endpoints via `display_name(slug)`.

This is a non-breaking change — existing clients ignore
the new field. The frontend `SegmentScore` type gains an
optional `name: string` field.

### 3. Frontend: render the name everywhere

- `frontend/app/components/ScoreboardTable.tsx`: the
  Segment column shows `name` (falls back to slug) with
  the slug as a small subscript for technical users.
- `frontend/app/components/RegimeQuadrant.tsx` /
  `SegmentBadge.tsx`: badge text shows the name; the
  tooltip (`title` attribute) shows the slug.
- `frontend/app/segment/[slug]/page.tsx`: `<h1>` shows
  the name; add a `<p>` underneath with the slug in
  monospace for technical reference.
- `frontend/app/components/QuadrantTickerList.tsx`:
  the list's `aria-label` uses the name.
- `frontend/app/components/Sparkline.tsx` /
  `SparklineForSegment.tsx`: `aria-label` uses the name
  instead of the slug (currently reads "Score trend from
  65.9 to 73.6 over 10 months" — adding the segment
  name makes it self-describing for screen readers).

### 4. Score column: rename + tooltip

- Column headers `near / med / long` → `B·near / B·med / B·long`
  (the `B` prefix makes the score explicit at a glance).
- Add a small `?` icon button to the right of each header,
  with a `title` attribute containing the explanation
  tooltip:

  ```
  B(s, h): binding score in [0, 100].
  5 weighted sub-scores per methodology §1-3:
  lead_time_growth, capacity_tightness,
  geo_concentration, regulatory_friction,
  demand_signal.
  
  ≥ 70  binding bottleneck (PEAKING/PEAKED/RESOLVING)
  ≥ 50  basket-eligible (screener filter)
  < 50  watchlist only
  
  B' (momentum): 6mo backward delta in B.
  ```

  This matches the existing tooltip pattern in
  `RegimeBadge.tsx:14` (`title={...}`) and
  `QuadrantTickerList.tsx:69` — no new dep.

- The tooltip text is a small constant in a new
  `frontend/app/lib/score_help.ts` so the same string is
  reused across scoreboard / segment page / manual.

### 5. Don't change the methodology doc

The user wants UI affordance, not a methodology rewrite.
The research/04_scoring_methodology.md already has §7.6
documenting the 7-cell regime table (which includes the
B≥70 binding threshold). No edits needed there.

---

## Files changed

**Backend (3 files):**
- `src/bottlewatch/app/segments_meta.py` (new) — the
  slug → name dict + `display_name()` function.
- `src/bottlewatch/app/api/segments.py` — add `name: str`
  to `SegmentScore` and `SegmentDetail`; populate from
  `display_name()`.
- `src/bottlewatch/tests/test_api_segments.py` (new or
  extended) — assert `name` is populated in both list
  and detail responses.

**Frontend (5 files):**
- `frontend/app/lib/score_help.ts` (new) — the
  `SCORE_HELP` tooltip string + a `displayName(slug)`
  helper that pulls from a small hardcoded map.
  (Mirrors the backend mapping; the canonical source
  is the API response, this is the fallback when the
  segment isn't in the API yet — e.g. ticker pages
  that have a segment slug without a score row.)
- `frontend/app/lib/api.ts` — add `name?: string` to
  `SegmentScore` and `SegmentDetail` types.
- `frontend/app/components/ScoreboardTable.tsx` —
  rename column headers to `B·near/med/long`, add the
  `?` tooltip, render name in the Segment column.
- `frontend/app/components/RegimeQuadrant.tsx` /
  `SegmentBadge.tsx` — render name in badge, slug in
  title attribute.
- `frontend/app/segment/[slug]/page.tsx` — render name
  in `<h1>`, slug in a small `<p>` underneath.
- `frontend/app/components/QuadrantTickerList.tsx` —
  use name in aria-label.
- `frontend/app/components/Sparkline.tsx` /
  `SparklineForSegment.tsx` — include name in aria-label
  if available.

**Tests:**
- Backend: a new spec for the name field.
- Frontend: extend `SparklineForSegments.test.tsx` /
  add a small spec for the new tooltip text.

---

## Reuse / patterns

- `display_name()` mirrors the `SEGMENT_TO_ROLE_CLASS`
  pattern in `app/score/ontology_segments.py` — hardcoded
  dict, single function accessor, slug fallback.
- The `?` tooltip uses the same `title=` attribute as
  `RegimeBadge.tsx` and `QuadrantTickerList.tsx` — no
  new dep, no popover component.
- Backend `SegmentScore.name` is added as an optional
  field; existing clients that don't read it are
  unaffected.

---

## What this plan does NOT do

- No methodology doc changes (the 7-cell table in
  `research/04_scoring_methodology.md` §7.6 already
  documents B ≥ 70 as the binding threshold).
- No new dependencies (no Popover, no tooltip library).
- No mobile-specific affordance — `title=` works
  equally on desktop hover and mobile long-press.
- The scoreboard's `Data` and `Trend` columns keep
  their current labels (no ambiguity there).

---

## Verification

- `make test` (Python): new spec passes; coverage stays
  above 80% threshold.
- `cd frontend && pnpm test`: extended specs pass.
- `cd frontend && pnpm exec tsc --noEmit`: clean.
- Manual: `make web` + `make api` running, hit
  `/scoreboard`:
  - Segment column shows human names (e.g.
    "Transformers & Switchgear (T&D)").
  - Slug shown as small grey subscript.
  - Column headers read "B·near / B·med / B·long".
  - `?` icon next to "B·near" shows the tooltip on
    hover.
- Hit `/`: quadrant badges show names, not slugs.
- Hit `/segment/transformers_tnd`: heading reads
  "Transformers & Switchgear (T&D)".
