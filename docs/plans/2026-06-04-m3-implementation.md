# M3 Implementation — Progress Summary

**Date:** 2026-06-04
**Status:** ~80% complete — backend done, frontend mostly done, last few TypeScript errors to fix

---

## Completed

### Backend (all done, all tests passing)
- [x] `Thesis` + `ScoreHistory` ORM models added to `db/models.py`
- [x] `db/__init__.py` exports updated
- [x] `0003_thesis.py` alembic migration
- [x] `0004_score_history.py` alembic migration
- [x] `GET/POST/DELETE /api/v1/thesis` in `thesis.py`
- [x] `GET /api/v1/tickers/{ticker}` in `tickers.py`
- [x] `GET /api/v1/map/{slug}` in `map.py` (with upstream/downstream BFS, companies, eta, thesis_count)
- [x] `GET /api/v1/scores/history` in `scores.py`
- [x] `recompute_scores.py` wired to read/write score_history + 12-month prune
- [x] CORS updated to `["GET", "POST"]` in `main.py`
- [x] `thesis.router` registered in `main.py`
- [x] All tests pass (160 passed, 1 unrelated pre-existing failure in `test_validate_ontology.py`)

### Frontend (mostly done, build has TypeScript errors to fix)
- [x] `api.ts` extended with M3 types + fetchers (`getTicker`, `getMapNode`, `getScoreHistory`, `listThesis`, `saveThesis`, `deleteThesis`)
- [x] `NO_DATA` added to `Regime` type in `api.ts`
- [x] `layout.tsx` updated with nav links (Quadrant, Scoreboard, Tickers, Map, Thesis)
- [x] `/tickers/page.tsx` — filterable screener table
- [x] `/tickers/[ticker]/page.tsx` — ticker detail page
- [x] `/map/page.tsx` — value chain node list + side panel
- [x] `/thesis/page.tsx` — TipTap editor + list of notes
- [x] `lib/store.ts` — Zustand store for /map focus path

### Ops
- [x] `launchd/com.bottlewatch.refresh.plist`
- [x] `launchd/com.bottlewatch.recompute.plist`
- [x] `launchd/install.sh`
- [x] `launchd/uninstall.sh`
- [x] `Makefile` updated with `schedule` and `unschedule` targets

---

## Remaining Work

### Frontend TypeScript errors (fix manually or with next session)
1. `/frontend/app/map/page.tsx:47` — TypeScript error in `bfs` function. Fix: change `depth: number` param to `maxDepth: number` and use explicit `Array<[string, number]` type annotation. **Already edited but build not re-run.**
2. Need to run `pnpm build` to confirm clean build
3. The `prose` class used in thesis page requires `@tailwindcss/typography` plugin — may need to add to `tailwind.config.ts`

### Frontend TypeScript errors to fix:
```
./app/map/page.tsx:47 — if (d >= maxDepth) — `d` is inferred as `string | number` because `frontier.shift()` returns `string | number`
Fix: add explicit type: `const frontier: Array<[string, number]> = [[start, 0]]`
```

### Other fixes still needed:
```
./app/components/RegimeBadge.tsx — NO_DATA key exists but Regime type was missing it — FIXED in api.ts
./app/map/page.tsx — same type narrowing issue — FIXED but not rebuilt
```

---

## To verify when ready to continue:

1. Run `cd frontend && pnpm build` to confirm clean build
2. Run `make db-upgrade` to apply migrations (or `uv run alembic upgrade head`)
3. Run `uv run pytest` to confirm all tests pass
4. Run `make web` + `make api` to smoke-test the new pages
5. `make schedule` to install launchd agents

---

## Files changed (M3 delta)

**Backend:**
- `src/bottlewatch/app/db/models.py` — added Thesis + ScoreHistory
- `src/bottlewatch/app/db/__init__.py` — exports
- `src/bottlewatch/app/api/thesis.py` — NEW
- `src/bottlewatch/app/api/scores.py` — added `/scores/history`
- `src/bottlewatch/app/api/tickers.py` — added `/tickers/{ticker}`
- `src/bottlewatch/app/api/map.py` — added `/map/{slug}`
- `src/bottlewatch/app/main.py` — CORS POST + thesis router
- `src/bottlewatch/jobs/recompute_scores.py` — score history wiring
- `alembic/versions/0003_thesis.py` — NEW
- `alembic/versions/0004_score_history.py` — NEW
- Tests: `test_api_thesis.py`, `test_api_scores_history.py`, `test_api_tickers_detail.py`, `test_api_map_node.py`, `test_score_history_job.py` — all NEW

**Frontend:**
- `frontend/app/lib/api.ts` — M3 types + fetchers
- `frontend/app/layout.tsx` — nav links
- `frontend/app/tickers/page.tsx` — NEW
- `frontend/app/tickers/[ticker]/page.tsx` — NEW
- `frontend/app/map/page.tsx` — NEW
- `frontend/app/thesis/page.tsx` — NEW
- `frontend/app/lib/store.ts` — NEW

**Ops:**
- `launchd/com.bottlewatch.refresh.plist` — NEW
- `launchd/com.bottlewatch.recompute.plist` — NEW
- `launchd/install.sh` — NEW
- `launchd/uninstall.sh` — NEW
- `Makefile` — schedule + unschedule targets
