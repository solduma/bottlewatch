# Plan: Full Value Chain (MAP) page

Date: 2026-06-12
Status: In plan mode — awaiting approval before implementation

---

## Background

User asked to "implement Value Chain (MAP)". Investigation
shows the page already exists with a React Flow graph,
sidebar, and BFS-traversal upstream/downstream paths — but
the page is **completely blank in the browser** because the
relative `fetch("/api/v1/map")` call goes to the Next.js
dev server (port 3000, returns 404) instead of the FastAPI
backend (port 8000).

User picked **"Full MAP page"** in the AskUserQuestion
choice: fix + essential features + cohort heatmap + export
to PNG.

---

## Approach

Five tiers, in priority order. Tier 1 alone makes the page
work; tiers 2-4 add the features that turn the page from
"renders" to "useful".

### Tier 1 — Fix what's broken (essential)

The current page is broken in three ways:

1. **Fetch is wrong.** `MapPage` does
   `fetch("/api/v1/map")` directly, bypassing the `API_BASE`
   constant. Add a `getMap()` helper to `lib/api.ts` (alongside
   `getTicker`, `getSegment`, etc.) and use it. Mirrors
   the existing pattern; no new behavior.

2. **Snake_case slugs everywhere.** Sidebar shows
   `transformers_tnd`, `advanced_node_fabs`, etc. Use
   `displayName(slug)` from `lib/score_help.ts` to render
   the human title, with the slug as a 10px monospace
   subscript and as the `title` attribute. The map's node
   labels in `00_value_chain.json` are mixed-case already
   (e.g. "advanced-node fabs") so the visual is closer to
   correct than the scoreboard was, but still inconsistent.

3. **Companies aren't clickable.** Sidebar shows chips with
   ticker symbols, but they're spans. Wrap each in
   `<Link href="/tickers/{ticker}">`. Already in place on
   `/tickers` listing.

### Tier 2 — Search + sector filter (essential UX)

On a 64-node graph, finding a specific node is hard. Add:

- **Search bar** above the graph. Type → highlight nodes
  whose label or slug contains the query (case-insensitive).
  Click a result → select that node (sets `selected`, opens
  the sidebar).
- **Sector filter chips** next to the search bar: All /
  Materials / Hardware / Infrastructure / Downstream. Toggling
  a sector hides nodes outside it (and their incident
  edges). React Flow supports this via
  `nodes.filter(...).map(...)` in the flowNodes memo.
- The current node count is shown in the footer
  ("32 of 64 visible") so the user knows the filter is
  active.

State lives in `useMapStore` (Zustand) which already exists
for focus state. Add `searchQuery` and `sectorFilter` to it.

### Tier 3 — Cohort heatmap (the distinctive feature)

The current map shows each node's *own* regime. The cohort
heatmap lets the user pick one segment from a dropdown and
recolor the entire DAG to show that segment's perspective:

> "If I'm a transformers_tnd investor, which upstream nodes
> are my risk?"

Implementation:

- A `<select>` next to the search bar: "View as: <segment
  | none>". Default "none" (current behavior).
- When a segment is picked, the client recomputes a
  *contribution map*: for each upstream node, score = the
  picked segment's score, color = regime of picked segment
  (or "NO_DATA" if the upstream node doesn't carry a score
  — those nodes render grey).
- A legend below the graph: "Colored by <segment> regime. The
  currently selected segment is outlined in blue."

This is **client-side only** — the existing `/api/v1/map`
response already includes each node's regime, so we just
remap the color field based on the chosen segment. No
backend changes.

The "right" feature would be a "blast radius" view: for each
upstream node, compute its *contribution weight* to the
chosen segment. But the value chain JSON doesn't carry
per-edge weights (just `role_kind: "supplies"`), so a
contribution score would be hand-rolled. Skipping for now;
the simpler "recolor by segment" is the v1.

### Tier 4 — Export to PNG (nice-to-have)

"Save this view" is a small UX win. Use the browser's
`<a download>` with a data URL of a serialized SVG. Two
approaches:

- **(a)** Find the React Flow `<svg>` on the page, serialize
  it, build a data URL, trigger download. Pure browser API,
  no new dep, ~30 lines.
- **(b)** Use `html-to-image` or `dom-to-image` to capture
  the full graph with CSS. Better fidelity but adds a dep.

Pick (a) — it's the lighter weight and the React Flow SVG
is already self-contained. White-bg fill so the exported PNG
isn't transparent.

Button placement: top-right of the graph panel,
next to the search/filter controls. Filename:
`bottlewatch-chain-YYYY-MM-DD.png`.

### Tier 5 — Comparison (skipped)

Side-by-side comparison of two segments is a much larger
feature (separate DAG, separate sidebar, separate
comparison logic). Out of scope for this round. If the user
wants it, it'd be its own plan.

---

## Files changed

**Frontend (5 files modified, 1 new):**

- `frontend/app/lib/api.ts` — add `getMap()` helper that
  uses `${API_BASE}/api/v1/map`. (Bug fix.)
- `frontend/app/lib/store.ts` — extend `useMapStore` with
  `searchQuery`, `sectorFilter`, `cohortSegment`,
  `cohortSegment.set(id | null)`. State for tiers 2-3.
- `frontend/app/components/MapSearch.tsx` (new) — the
  search input + sector chips + cohort dropdown. Pure
  presentational; reads/writes through `useMapStore`.
- `frontend/app/components/MapNodeSidebar.tsx` — use
  `displayName`, wrap company chips in `<Link>`, show the
  depth+regime on upstream/downstream buttons.
- `frontend/app/components/ValueChainGraph.tsx` — apply
  search/sector filter to `flowNodes`; recolor by
  cohort; add PNG export button + handler. The component
  grows but stays cohesive.
- `frontend/app/map/page.tsx` — mount the new `MapSearch`
  component above the graph; pass it through to the
  sidebar layout.

**No backend changes** — the existing `/api/v1/map` and
`/api/v1/map/{slug}` endpoints cover everything we need.

**No new dependencies** — PNG export uses the browser's
native `<a download>` + `URL.createObjectURL`.

**No new tests** for the JSX components (the frontend has
no React test runner; visual verification is the gate per
the convention in `chainLayout.ts`'s comment).

---

## Verification

- `pnpm test` (vitest): unchanged. The frontend has no React
  tests; the new components are pure JSX.
- `pnpm exec tsc --noEmit`: clean.
- Python: `make test` — unchanged, no backend edits.
- Manual, with `make api` + `make web` running, visit
  `/map`:
  - **Page renders** the full 64-node DAG (currently blank
    — first thing to verify).
  - **Click any node** → sidebar populates with regime, score,
    B', upstream/downstream paths, ETA, companies, thesis
    count. Names show as "Transformers & Switchgear (T&D)"
    with the slug subscript.
  - **Click a company chip** in the sidebar → navigates to
    `/tickers/[ticker]`.
  - **Search "transformer"** in the search bar → only
    matching nodes stay highlighted; clicking a result
    selects the node.
  - **Toggle "Materials" sector** → only Materials nodes
    visible; edges between visible nodes still drawn.
  - **Cohort: pick `transformers_tnd`** → all nodes
    re-colored by transformers_tnd's regime. The legend
    updates.
  - **Export PNG** → file downloads as
    `bottlewatch-chain-2026-06-12.png` with the graph.
- Headless Chrome screenshot of `/map` before/after — should
  show the DAG filling the panel.
