# Bottlewatch — M2 Implementation Plan

**Status:** Plan finalized (open questions resolved)  
**Milestone:** M2 — Backend API + First Frontend Pages  
**Date:** 2026-06-04

---

## 1. Current State (Post-M1)

### Backend (FastAPI)
Already implemented:
- `/api/v1/health` — DB liveness + last recompute timestamp
- `/api/v1/segments` — list of all (segment, horizon) score rows
- `/api/v1/segments/{slug}` — segment detail (all 3 horizons + sub-scores + recent signals)
- `/api/v1/signals?segment=...` — raw signal list
- Scoring engine: `compute_segment_score()` + `classify()` + `recompute_scores` job
- All 10 data adapters registered

### Frontend (Next.js 15)
Already implemented:
- `/` — Sortable scoreboard table (10 segments × 3 horizons)
- `/segment/[slug]` — Sub-scores bars, horizon cards, recent signals table
- `api.ts` typed fetchers, `RegimeBadge` component

---

## 2. M2 Scope (Refined per Open Questions)

### 2.1 Backend: New API Endpoints

| Endpoint | What it returns | Priority |
|---|---|---|
| `GET /api/v1/segments?horizon=near\|med\|long` | **MOD**: Add `?horizon=` query param to existing endpoint; filters to 10 rows | **P0** |
| `GET /api/v1/scores/regime` | Quadrant payload: per-(segment, horizon): B, B', regime, regime_confidence, data_completeness, computed_at | **P0** |
| `GET /api/v1/tickers` | Universe list with per-ticker regime annotations (read from ontology ABox, fall back to CSV) | **P1** |
| `GET /api/v1/screener?side=long\|short&horizon=` | **Segment-level** rows. Long excludes RESOLVING (hard guard). Short returns RESOLVING ranked by B × \|B'\|. | **P1** |
| `GET /api/v1/map` | **JSON-only stub** of the value chain DAG (nodes + edges with regime injected). M3 adds React Flow. | **P2** |
| `GET /api/v1/eta` | Resolution ETA per segment (directional: <12mo / 12-24mo / >24mo, from static JSON or hardcoded) | **P2** |

**Decisions:**
- **Screener = segment-level.** One row per (segment, horizon) that passes the filter. Ticker-level rows are M3.
- **Map = JSON-only stub.** No frontend rendering in M2.
- **Old table preserved at `/scoreboard`.** `ScoreboardTable.tsx` moves there (a single new route).
- **Segment basket implication = read-only string.** No screener API call, no TipTap. Static sentence derived from regime.

### 2.2 Frontend: Regime Quadrant (Primary View)

Replace `frontend/app/page.tsx` with the **2×2 Regime Quadrant**.

**Layout (per plan §5):**
```
┌─────────────────────────────────────────────────────┐
│  Horizon toggle:  [near] [med] [long]                 │
│  Links: [Quadrant] [Scoreboard] [Map] (M3)           │
├─────────────────────────────────────────────────────┤
│  proactive longs (EMERGING) │ shorts (RESOLVING)    │
│  watchlist (rising from low)│                       │
├─────────────────────────────────────────────────────┤
│  2×2 Quadrant (B × B' plane)                        │
│                                                     │
│        B' ▲                                         │
│           │  EMERGING    PEAKING     RESOLVING      │
│   +tight  │  (low B)     (high B)    (high B)       │
│           ├──────────────────────────────────────   │
│   stable  │  EMERGING    STABLE      RESOLVING      │
│           │  (low B)     (med B)     (low B)         │
│   -loose  │                                         │
│           └────────────────────────► B               │
└─────────────────────────────────────────────────────┘
```

**Above the quadrant:** three derived lists (computed client-side from the segments data).
**Horizon toggle:** re-fetches `/api/v1/segments?horizon=...`.
**Click badge →** `/segment/[slug]`.

### 2.3 Frontend: Segment Detail Page Polish

Update `frontend/app/segment/[slug]/page.tsx`:
- Add a **regime summary card** at the top: single sentence like "RESOLVING: not a long candidate. Hard guard fires."
- **No dynamic screener call.** The implication is a static lookup table in the frontend.

### 2.4 Frontend: New Routes

- `/scoreboard` — Move `ScoreboardTable.tsx` here (sortable table, alt view).

---

## 3. Implementation Order (TDD: Tests → Backend → Frontend)

```
Step 1: Write failing tests for new endpoints
        - test_scores_regime.py: shape, all 3 horizons, all regimes
        - test_tickers.py: returns > 0 rows, has ticker + segment
        - test_screener.py: long excludes RESOLVING; short returns only RESOLVING
        - test_map.py: returns nodes + edges arrays
        - test_eta.py: returns ETA per segment
        - test_segments_horizon_filter.py: ?horizon= filter works
        → verify: all fail with NotImplementedError or 404

Step 2: Backend — add ?horizon= filter to /api/v1/segments
        → verify: tests pass, ?horizon=near returns 10 rows

Step 3: Backend — /api/v1/scores/regime
        → verify: tests pass, shape matches frontend needs

Step 4: Backend — /api/v1/tickers
        → verify: tests pass, universe populated

Step 5: Backend — /api/v1/screener (long + short)
        → verify: tests pass, hard guard verified

Step 6: Backend — /api/v1/map (stub) + /api/v1/eta (stub)
        → verify: tests pass, return static data

Step 7: Frontend — write component tests for RegimeQuadrant, HorizonToggle, SegmentBadge
        → verify: tests fail (no components yet)

Step 8: Frontend — implement HorizonToggle + SegmentBadge
        → verify: component tests pass

Step 9: Frontend — implement RegimeQuadrant
        → verify: component tests pass, quadrant renders with mock data

Step 10: Frontend — rewrite / as RegimeQuadrant
         → verify: page loads, badge click navigates to segment

Step 11: Frontend — derive 3 lists above quadrant
         → verify: lists populate from segments data

Step 12: Frontend — move ScoreboardTable to /scoreboard route
         → verify: /scoreboard renders the old table

Step 13: Frontend — polish /segment/[slug] with regime summary card
         → verify: page shows regime call

Step 14: Integration — make api + make web, navigate the flow
         → verify: / → click EMERGING → /segment/[slug] → back, no errors
```

---

## 4. Key Design Decisions

### Horizon filter: query param
`/api/v1/segments?horizon=near` returns 10 rows. The quadrant re-fetches on toggle. Smaller payload, no client-side filtering.

### Screener hard guard: backend
The `screener` endpoint filters out RESOLVING segments for `side=long`. The frontend shows the guard firing (grayed-out segment with tooltip) rather than silently filtering.

### Score history: accept the limitation
`recompute_scores` still passes `b_history=None`. B' = 0 for all segments on first run. The quadrant renders with all segments in STABLE/PEAKED — no EMERGING/RESOLVING cells. Document this in the UI ("Momentum requires 6mo of nightly recomputes; first run = 0 history").

**This is the known limitation.** Adding `score_history` storage is M3 work.

### Map endpoint: JSON-only stub
`/api/v1/map` returns the JSON from `research/00_value_chain.json` with regime colors injected. No `/map` frontend page in M2. M3 adds React Flow.

### Old table: preserved at /scoreboard
`ScoreboardTable.tsx` moves to a new `/scoreboard` route. A small link in the page header lets the user switch between the quadrant and the table.

### Caching: deferred
No `lru_cache` for M2. The endpoints are fast (SQLite + 10-30 row reads) and only the dashboard hits them. Add caching in M3 if we see actual load.

### Routing structure: unchanged
`app/main.py` adds 5 more `include_router` calls under `/api/v1`. No new structure needed.

---

## 5. Files to Touch

### Backend (new + modified)
```
src/bottlewatch/app/api/
├── scores.py          # NEW: /scores/regime
├── tickers.py         # NEW: /tickers
├── screener.py        # NEW: /screener
├── map.py             # NEW: /map (stub)
├── eta.py             # NEW: /eta (stub)
├── services.py        # MOD: add service functions for all new endpoints
└── segments.py        # MOD: support ?horizon= filter

src/bottlewatch/app/main.py
└── MOD: include_router() for the 5 new routers
```

### Frontend (new + modified)
```
frontend/app/
├── page.tsx                      # MOD: replace table with RegimeQuadrant
├── segment/[slug]/page.tsx       # MOD: add regime summary card
├── scoreboard/page.tsx           # NEW: move ScoreboardTable here
├── components/
│   ├── RegimeQuadrant.tsx        # NEW
│   ├── HorizonToggle.tsx         # NEW
│   ├── SegmentBadge.tsx          # NEW
│   ├── ScoreboardTable.tsx       # KEEP (used by /scoreboard)
│   └── RegimeBadge.tsx           # KEEP
└── lib/api.ts                    # MOD: add fetchers + ?horizon= support
```

---

## 6. Verification Criteria

**Backend tests:**
1. `GET /api/v1/segments?horizon=near` returns 10 rows
2. `GET /api/v1/segments?horizon=med` returns 10 rows
3. `GET /api/v1/segments?horizon=long` returns 10 rows
4. `GET /api/v1/segments?horizon=bogus` returns 400
5. `GET /api/v1/scores/regime` returns all 30 rows with B, B', regime, regime_confidence
6. `GET /api/v1/tickers` returns > 0 rows with ticker, segment fields
7. `GET /api/v1/screener?side=long&horizon=near` returns 0 rows with regime == RESOLVING
8. `GET /api/v1/screener?side=short&horizon=near` returns only RESOLVING rows, sorted by B × |B'| desc
9. `GET /api/v1/map` returns `{nodes: [...], edges: [...]}` with regime on each node
10. `GET /api/v1/eta` returns per-segment ETA strings

**Frontend:**
1. `/` shows a 2×2 quadrant with colored segment badges
2. Horizon toggle re-fetches and updates the quadrant
3. Click a badge → navigates to `/segment/[slug]`
4. `/segment/[slug]` shows the regime summary card
5. `/scoreboard` shows the sortable table
6. Header link between Quadrant ↔ Scoreboard works
7. Header still shows "DB ok · last score: [timestamp]"

**Integration:**
1. `make test` passes, coverage ≥ 80%
2. `make api` + `make web` running simultaneously
3. Navigate `/` → click badge → `/segment/[slug]` → back, no 404s, no console errors
4. `make ingest` populates real data; quadrant reflects it
5. `make recompute` updates scores; quadrant updates

---

## 7. Known Limitations (M2 → M3)

1. **Momentum is always 0.0** until 6mo of nightly recomputes accumulate. EMERGING and RESOLVING cells will be empty in the meantime. Document this in the UI.
2. **No map page** in M2. The `/api/v1/map` stub exists for frontend testing, but no React Flow UI.
3. **No thesis editor.** Segment detail has a static implication string, not a TipTap editor.
4. **No scoreboard charts.** Recharts is M3 per the plan.
5. **No caching.** All endpoints hit the DB on every request. Fine for a personal dashboard.
