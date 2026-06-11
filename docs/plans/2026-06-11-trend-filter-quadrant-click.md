# Plan: Trend range filter + quadrant sector click → ticker list

Date: 2026-06-11
Status: In plan mode — awaiting approval before implementation

---

## Background

User asked for two related UX improvements on the dashboard:

1. **Trend range filter** — a small toggle (1mo / 3mo / 6mo / 1y) on the
   `Trend` column header of the scoreboard to switch the sparkline
   time window. Currently the value is hardcoded to 6 months in
   `ScoreboardTable.tsx:72`.

2. **Click sector in quadrant → ticker list** — clicking a segment
   badge in the 2x2 quadrant (e.g. clicking "transformers_tnd" in
   the PEAKING cell) should expand a list of that segment's tickers
   inline, not navigate to `/segment/[slug]`. Per user-confirmed
   preview: a list of `ticker · name · exposure%` rows underneath
   the badges, click again to collapse.

Both changes are pure frontend. No backend changes needed — the
API already supports:
- `?months=1..36` on `/api/v1/scores/history` (the batched sparkline
  endpoint)
- `?segment=X` on `/api/v1/tickers` (returns the 10-16 tickers
  for a segment)

---

## Feature 1: Trend range filter

### Approach

Add a state hook in `ScoreboardTable.tsx` for the selected range,
defaulting to `6`. Render a small inline segmented control inside
the existing `<th>Trend</th>` cell. Pass the value to
`useBatchedScoreHistory`.

### Files changed

- `frontend/app/components/ScoreboardTable.tsx` — add `trendMonths`
  state, segmented control in the `<th>`, pass through to
  `useBatchedScoreHistory`. New derived key in the dependency
  string so a range change triggers a refetch.
- `frontend/app/components/SparklineForSegments.test.tsx` —
  add a test asserting that changing the `months` argument
  triggers a refetch (the existing "does not refetch" test covers
  the same-args case; this is the different-args mirror).

### UI shape

The control lives in the existing `<th>Trend</th>` cell so it
visually associates with the column. The header is currently a
plain "Trend" label. Replace it with:

```tsx
<th className="px-3 py-2" style={{ width: 120 }}>
  <div className="flex items-center gap-1">
    <span className="text-xs uppercase tracking-wide text-gray-500">Trend</span>
    <div className="ml-auto inline-flex rounded border border-gray-200 text-[10px]">
      {([1, 3, 6, 12] as const).map((m) => (
        <button
          key={m}
          type="button"
          onClick={() => setTrendMonths(m)}
          className={`px-1.5 py-0.5 ${
            trendMonths === m ? "bg-gray-900 text-white" : "text-gray-500 hover:bg-gray-50"
          }`}
          aria-label={`${m} months`}
        >
          {m < 12 ? `${m}mo` : "1y"}
        </button>
      ))}
    </div>
  </div>
</th>
```

The cell's `width: 120` stays so the column is consistent across
range changes. The "1y" label is shorthand for 12 months.

### State and re-key

`useBatchedScoreHistory` already uses
`${segments.join(",")}|${horizon}|${months}` as its re-fetch key,
so changing `months` will trigger a refetch automatically.

### Edge case: short history

If a segment was added mid-2025, the 1y view for it will only
show 6-8 months of data. The sparkline renders whatever the API
returns, so the chart will look like 1y data for established
segments and shorter for newer ones. The aria-label
"over N months" already exposes this honestly; no fix needed.

---

## Feature 2: Quadrant sector click → inline ticker list

### Approach

Make the `SegmentBadge` clickable to *toggle* an expansion of
ticker rows. The current implementation wraps the badge in a
`<Link href="/segment/[slug]">`. Replace the Link with a
`<button>` for the score number (the part that toggles), and
keep navigation via a small "→" link or shift-click behavior
so existing drilldown still works.

The `useBatchedScoreHistory` pattern from Feature 1 mirrors what
we need: one fetch per cell activation, cached per segment.

### Files changed

- `frontend/app/components/SegmentBadge.tsx` — split into two
  parts: the badge body (now a `<button>` that fires
  `onToggle`) and an optional navigation link. Pass an
  `onToggle?: () => void` prop and an `expanded?: boolean` prop
  so the parent can control the state. Keep the `href` as a
  fallback for `Cmd/Ctrl+click` semantics.

- `frontend/app/components/RegimeQuadrant.tsx` — track which
  segment (if any) is expanded in a `useState<{segment, cell} | null>`.
  When a badge is clicked, set/clear the state. Render the ticker
  list inline under the cell's badges when a segment is expanded.

- `frontend/app/lib/api.ts` — the `listTickers` fetcher is
  already there; no change.

- New `frontend/app/components/QuadrantTickerList.tsx` — small
  client component that:
  1. Calls `listTickers(segment)` on mount
  2. Renders rows: `ticker · name · exposure_pct% · link to /tickers/[ticker]`
  3. Handles loading / error / empty states consistently with
     other components

- New test `frontend/app/components/QuadrantTickerList.test.tsx`
  — fetch mock + assertion that the list renders, sort order
  by `exposure_pct` desc, "navigate to ticker" links work.

### UI shape

```
┌─────────────────────────────────┐
│ PEAKING (high B)                │
│ Hold or trim                    │
│ ┌──┐ ┌──┐ ┌──┐                   │
│ │73│ │70│ │68│  ← click one      │
│ └──┘ └──┘ └──┘                   │
│ ─────────────────────────────── │
│  ▲ click HUBB-72 again to close │
│  HUBB  Hubbell        exposure 80│
│  ETN   Eaton          exposure 75│
│  SU    Schneider      exposure 55│
│  ... (16 tickers total)         │
└─────────────────────────────────┘
```

Ticker rows are compact: `font-mono` ticker, name, exposure%.
Each row is a `<Link href="/tickers/[ticker]">` so clicking
navigates to the ticker detail.

### State ownership

`RegimeQuadrant` is a pure function component. Adding
`useState<{segment, cell} | null>` requires marking the file
"use client" (already is). No prop changes needed.

### Multiple cells, multiple segments

In principle two cells could each have an expanded segment.
A single state slot is enough because the user is unlikely to
want two expansions simultaneously; clicking a badge in cell B
collapses the one in cell A. Simpler than a map.

### Sort order

Sort tickers by `exposure_pct` desc (matches the conviction
basket construction rule in methodology §4). Show all 10-16 —
they fit comfortably in 200px of vertical space.

---

## What this plan does NOT do

- No backend changes. Both endpoints already support the inputs.
- No new dependencies (no new Tailwind classes beyond what's used
  elsewhere in the codebase).
- No changes to `/segment/[slug]` or `/tickers/[ticker]` pages.
- The Trend toggle stays on the scoreboard page only (not
  mirrored on `/tickers/[ticker]` where there's one sparkline
  per segment — keeping scope tight).

---

## Implementation order

1. Feature 1 first (smaller diff, isolated to ScoreboardTable).
2. Feature 2 second (touches SegmentBadge, RegimeQuadrant,
   and a new component).

---

## Verification

- `make test` (Python): unchanged, no new backend code.
- `cd frontend && pnpm test`: new vitest specs pass.
- `cd frontend && pnpm exec tsc --noEmit`: type-check clean.
- Manual: `make web` + `make api` running, navigate to
  `/scoreboard`:
  - Click 1mo / 3mo / 6mo / 1y toggle → sparklines refetch and
    redraw with different x-axis spread.
  - Navigate to `/` → click `transformers_tnd` in the quadrant →
    ticker list appears below the badges, sorted by exposure.
  - Click the same badge again → list collapses.
  - Click a different segment's badge → previous expansion closes,
    new one opens.
- Confirm existing /segment/[slug] navigation still works (the
  SegmentBadge retains an href for cmd/ctrl-click and a small
  "→" indicator on hover).
