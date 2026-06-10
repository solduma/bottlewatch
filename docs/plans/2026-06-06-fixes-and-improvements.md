# Plan: Fix all assessment findings and highest-leverage improvements

Date: 2026-06-06
Author: Claude Code
Status: ✅ Complete (closed 2026-06-06) — see "Final status" at end.

---

## Goal

Fix every `blocker` and `high` finding from the full assessment, then implement the top 5 highest-leverage improvements. The codebase is currently uninitialized (no commits), so there is no git history to scrub — we can simply remove `.env` from the working tree and be clean going forward.

---

## Principles

1. **Surgical changes** — every diff traces to one finding; no unrelated cleanup.
2. **Spec-driven** — threshold calibration and segment mapping are the only places where spec ↔ code can differ; pick one source of truth and document it.
3. **Test first where it catches a bug** — the slug-lookup bug and the threshold drift both need tests.
4. **No new abstractions** — centralize existing duplicated logic into a shared module; do not introduce a new framework.

---

## Phase 1: Security (blocker)

> These must be fixed before any deployment to a non-localhost host.

### 1.1 Remove `.env` from working tree and rotate keys

**What:** The `.env` file is in the working tree and contains live API keys (EIA, FRED, Comtrade) + a Postgres password. `.gitignore` already lists `.env`, so the file was created after the git init.

**Spec (current → target):**
- Input: `.env` file at project root.
- Output: No `.env` at project root; `.env.example` with placeholder comments; keys rotated on external services.
- Verify: `git ls-files .env` returns empty; `ls .env` returns "not found"; `.env.example` is tracked.

**Steps:**
1. `cp .env .env.example`
2. Strip all real keys from `.env.example`, replace with `<replace-with-your-key>` comments.
3. `rm .env`
4. User rotates keys on EIA, FRED, Comtrade, and Postgres (must be done by the user).
5. Verify `.env.example` is tracked and `.env` is not.

**Resolution (2026-06-06):** The plan's "delete + rotate" stance was overridden by the operator. The `.env` file was lost during a separate session; the operator asked to restore it (keys for EIA, FRED, Comtrade re-pasted in). The current state is: `.env` exists with the three live API keys, `.env.example` is the placeholder template, `.gitignore` excludes `.env`, and the pre-commit hook (item 1.3) refuses to stage it. Key rotation is deferred — the operator's call.

### 1.2 Fix CORS docstring / method mismatch in `app/main.py`

**What:** Docstring at `main.py:12` says "methods locked to `GET` in M2 (read-only API)" but code at `main.py:49` allows `POST`. POST is correct (thesis endpoint), so the docstring is stale.

**Spec:**
- Input: docstring at `main.py:12`.
- Output: docstring reads "methods locked to `GET` and `POST` in M2 (POST only for thesis endpoints; the rest of the API is read-only)".
- Verify: `grep -n "methods locked" src/bottlewatch/app/main.py` matches updated text.

**Status (2026-06-06):** ✅ Already done. Docstring at `main.py:12` reads "CORS: methods are `GET` plus `POST` in M2"; `allow_methods=["GET", "POST"]` at line 50. Pre-existing fix.

### 1.3 Add pre-commit hook to block `.env` staging

**What:** Prevent accidental re-add of `.env` in the future.

**Spec:**
- Input: `.env` file.
- Output: `.pre-commit-config.yaml` or a simple git pre-commit script that fails if `.env` is in the staged file list.
- Verify: `touch .env && git add .env && git commit` fails with descriptive error message.

**Decision:** A simple pre-commit script is enough; the project doesn't use `pre-commit` (not in `pyproject.toml`). Add a simple `.git/hooks/pre-commit` via an `install-hooks` Makefile target or document it.

**Status (2026-06-06):** ✅ Already done. `.githooks/pre-commit` exists and refuses to stage any path matching `.env` (8 mentions of `.env` in the file). `make install-hooks` target wires it. Pre-existing fix.

---

## Phase 2: Silent correctness bugs (user-facing, high impact)

> These bugs affect real data that the dashboard shows to the user.

### 2.1 Centralize segment ↔ value-chain-node translation, fix `tickers.py` companies bug

**What:** The value-chain JSON uses `transformers_switchgear` and `rack_scale_integration` as node ids, but the scoring layer uses `transformers_tnd` and `systems_rack_scale`. `map_mermaid.py:51-62` has `_NODE_TO_SEGMENT` but `tickers.py:215-220` does a direct `seg_to_node.get(seg)` lookup without translation, silently returning empty `companies` for those two segments.

**Spec:**
- Input: `seg_to_node.get(seg)` in `tickers.py:218`.
- Output: A shared `SEGMENT_TO_NODE_ID` mapping used by both `map_mermaid.py` and `tickers.py`, with the inverse used for `tickers.py` lookups.
- Verify: `test_api_tickers_detail.py` asserts `companies` is non-empty for HUBB (transformer ticker) and WEC (power/utility ticker with both segments).

**Steps:**
1. Create `src/bottlewatch/app/value_chain.py`:
   - `SEGMENT_TO_NODE_ID: dict[str, str]` — the inverse of `_NODE_TO_SEGMENT` from `map_mermaid.py`, but made authoritative.
   - `NODE_ID_TO_SEGMENT: dict[str, str]` — the forward mapping.
   - `load_value_chain_json() -> dict` — small helper, currently inlined in `tickers.py:213` and `map_mermaid.py:load_chain()`.
2. Replace `_NODE_TO_SEGMENT` in `map_mermaid.py` with an import from `value_chain`.
3. In `tickers.py:215-220`, use `SEGMENT_TO_NODE_ID.get(seg)` to find the node id, then look up companies.
4. Add test: `test_api_tickers_detail.py` checks `companies` for a ticker whose segment slug differs from its node id.

**Decision:** `app/value_chain.py` (new module) is the right place. It sits between `research/` artifacts and `app/` consumers, matching the "research artifacts → runtime" bridge pattern used by `app/score/ontology_segments.py`.

### 2.2 Remove stub adapters from the production registry

**What:** `sec_insider.py`, `sec_edgar.py`, and `epa_egrid.py` return hardcoded fake `RawSignal` data. They are registered in `app/ingest/__init__.py:88-107` and the orchestrator writes them to the DB every day. The tests assert the fake output, so CI is green for the wrong reason.

**Spec:**
- Input: 3 stub adapters registered in `_build_registry()`.
- Output: 3 adapters remain in the codebase but `is_configured()` returns `(False, "not yet implemented in M3")`; the orchestrator skips them at `SKIP` level.
- Verify: `test_api_tickers.py` or `test_refresh_daily.py` asserts no stub-adapter signals are present in the DB after a `refresh_daily` run; the 3 adapter-specific tests are updated to assert `is_configured` returns `False`.

**Steps:**
1. In each of `sec_insider.py`, `sec_edgar.py`, `epa_egrid.py`, change `is_configured()` to return `(False, "not yet implemented in M3")`.
2. The orchestrator already handles `is_configured` returning `False` — verify by reading `refresh_daily.py` logic.
3. Update the 3 adapter test files (`test_sec_edgar_adapter.py`, `test_sec_insider_adapter.py`, `test_epa_egrid_adapter.py`) to assert `is_configured()[0] is False`.
4. Add test in `test_refresh_daily.py` (or `test_fred_end_to_end.py` style): after running the orchestrator, assert no signals exist with `source in ("sec_edgar", "sec_insider", "epa_egrid")`.

### 2.3 Fix `_coerce_float` bare except and `None→0.0` silent substitution

**What:** `tickers.py:58-66` `_coerce_float` returns `None` on `InvalidOperation` or `ValueError`. The caller at `tickers.py:124,126` does `_coerce_float(...) or 0.0`, turning garbage into `0.0` exposure silently.

**Spec:**
- Input: `_coerce_float` returns `None` on parse failure.
- Output: `_coerce_float` raises `ValueError` on parse failure; caller propagates or explicitly falls back. For the ticker list endpoint, garbage becomes `None` in the JSON response (Pydantic allows `float | None`). For `exposure_pct`, it becomes `None` instead of `0.0`.
- Verify: `test_api_tickers.py` with a test row where `exposure_pct = "n/a"` → response contains `"exposure_pct": null`.

**Steps:**
1. Change `_coerce_float` to raise `ValueError` on parse failure.
2. Change callers to handle the exception:
   - `list_tickers()`: catch `ValueError`, log warning, set `exposure_pct=None`.
   - `get_ticker()`: same pattern.
3. Update `TickerRow.exposure_pct: float | None` (already typed as `float | None` — good, just need to stop substituting `0.0`).
4. Add test.

### 2.4 Fix `tickers.py` ETA "first segment" non-determinism

**What:** `tickers.py:248-251` picks `next(iter(segment_map))` for ETA lookup. If a ticker has multiple segments, the picked one is non-deterministic (dict iteration order is insertion order but insertion order depends on CSV row order).

**Spec:**
- Input: ticker with 2+ segments; `segment_map` dict.
- Output: Pick the segment with highest `exposure_pct` for ETA display; if all are `None`, pick the first.
- Verify: `test_api_tickers_detail.py` with a multi-segment ticker asserts ETA `segment` matches the highest-exposure segment.

**Steps:**
1. Replace `next(iter(segment_map))` with a helper that sorts by exposure_pct descending.
2. Add test.

### 2.5 Fix `tickers.py:221-222` bare `except Exception: pass`

**What:** A bare except swallows all errors when loading the value chain JSON. If the file is corrupt, the user sees an empty companies list with no warning.

**Spec:**
- Input: corrupt value-chain JSON or missing file.
- Output: Log a warning; return empty companies list (same behavior, but logged).
- Verify: Unit test with a temporarily unreadable JSON file asserts a warning is logged and companies is empty.

**Status (2026-06-06):** ✅ All five Phase 2 items already done in the codebase before this plan was reviewed.

- 2.1 — `app/value_chain.py` exists with `SEGMENT_TO_NODE_ID` / `NODE_ID_TO_SEGMENT` / `load_value_chain_json()`; `tickers.py` and `map_mermaid.py` import from it. `tickers.py:32` uses `from bottlewatch.app.value_chain import SEGMENT_TO_NODE_ID, load_value_chain_json`.
- 2.2 — All three stub adapters (`sec_edgar.py`, `sec_insider.py`, `epa_egrid.py`) return `(False, "not yet implemented in M3")` from `is_configured()`. `refresh_daily` logs them as SKIPPED.
- 2.3 — `_parse_exposure_pct` at `tickers.py:105` logs a warning and returns `None` on parse failure (no `None → 0.0` substitution). `TickerRow.exposure_pct` typed as `float | None`.
- 2.4 — Multi-segment tickers pick the highest-exposure segment for ETA (line 300 in the current `tickers.py`).
- 2.5 — No bare `except Exception: pass` in `tickers.py` or `map.py` (grep returns no matches).

---

## Phase 3: Regime threshold calibration & spec alignment

> The single biggest spec ↔ code drift. Must pick one source of truth.

### 3.1 Pin regime thresholds in a config file

**What:** Plan §7.2 documents (60, ±5); code in `regime.py:85-98` uses (70, +20/0/+30/-15). Both are in the repo and contradict each other.

**Spec:**
- Input: hardcoded thresholds in `regime.py`.
- Output: `research/06_regime_thresholds.json` with the chosen calibration; `regime.py` reads this at import time.
- Verify: Tests still pass; a test asserts that the JSON file round-trips to the same thresholds.

**Steps:**
1. Create `research/06_regime_thresholds.json`:
   ```json
   {
     "version": "M2-v1",
     "b_threshold": 70,
     "b_prime": {
       "high": {"min": 20, "regime": "PEAKING"},
       "peak": {"min": 0, "regime": "PEAKED"},
       "resolving": {"max": -15, "regime": "RESOLVING"},
       "fast_resolve": {"max": -50, "regime": "RESOLVING", "fast_resolve": true},
       "emerging": {"min": 30, "regime": "EMERGING"},
       "stable": {"min": -15, "max": 30, "regime": "STABLE"},
       "resolving_from_low": {"max": -15, "b_max": 30, "regime": "RESOLVING_FROM_LOW"}
     },
     "no_data_threshold": 0.4,
     "fast_resolve_threshold": -50
   }
   ```
   (Or a simpler flat structure that matches the code's current branching.)
2. Load in `regime.py` at module import time. Fail fast on malformed JSON (better than a hardcoded default).
3. Keep the 6-cell table code but read numbers from config.
4. Update `docs/plans/2026-06-03-bottlewatch-v1.md` §7.2 with a note: "Calibrated in M2 to the thresholds in `research/06_regime_thresholds.json`; the (60, ±5) in this section is the historical placeholder."
5. Update `research/04_scoring_methodology.md` §7.6 with the same note.

**Decision:** The code's calibration (70, ±20/0/±30/-15) is the working model. The plan's (60, ±5) was explicitly called a placeholder. We treat the JSON config as the single source of truth and update the plan docs to point to it.

### 3.2 Test coverage for threshold calibration

**What:** Neither the plan's (60, ±5) nor the code's (70, ±20/0/±30/-15) thresholds have tests that would catch an accidental drift.

**Spec:**
- Input: a change to `research/06_regime_thresholds.json`.
- Output: a test that loads the JSON and asserts the classify() function produces the expected regimes for the 7 canonical (B, B') boundary pairs.
- Verify: If the JSON thresholds change, the test fails with a clear diff.

**Steps:**
1. In `test_score_regime.py`, add a test that reads `research/06_regime_thresholds.json` and asserts `classify()` for each boundary pair.
2. Add a second test that asserts the JSON version field matches the current expected version (forces a conscious bump on recalibration).

**Status (2026-06-06):** ✅ Both Phase 3 items already done.

- 3.1 — `research/06_regime_thresholds.json` exists with `version: "M2-v1"`, the 6 cells in plan §7.6 order, the `no_data_threshold: 0.4`, and the `b_prime_max_inclusive` flag for the lowest cell. `regime.py` reads it at import time.
- 3.2 — `test_score_regime.py:101` `test_thresholds_file_loads_with_expected_version` and `:109` `test_thresholds_file_has_all_seven_cells` both assert against the JSON file directly.

---

## Phase 4: Data pipeline hardening

### 4.1 Fix capacity_tightness window mismatch

**What:** `_power_tightness()` in `extractors.py:90-120` sums ALL `planned_capacity_mw` in the passed window. The recompute job passes 730 days of signals (`_LOOKBACK_DAYS = 730`), so it sums planned additions through ~2028 — not the 24-month window the methodology calls for. The docstring at `extractors.py:101-104` acknowledges this.

**Spec:**
- Input: signals with `planned_capacity_mw` values spanning 2+ years.
- Output: `_power_tightness` filters `planned_capacity_mw` to `observed_at <= now + 730 days` (or a configurable forward window). The sum is capped to the forward-looking 24 months.
- Verify: `test_score_extractors.py` with 3 years of planned additions asserts only the first 24 months are summed.

**Steps:**
1. Pass `now: date` into `capacity_tightness()` (it's already in `extractors.py:46` via the recompute job).
2. In `_power_tightness`, filter `planned_capacity_mw` to `observed_at <= now + 730 days` (or better, `observed_at <= now + 730` is wrong — the signal's `observed_at` is the report date, not the planned operation year. The signal carries `planned_operation_year` in `value_text` or we need a new field).
3. **Wait — this is more complex.** The `planned_capacity_mw` signal's `observed_at` is the EIA 860M report month, not the planned operation year. The planned year is in the signal's `value_text` or metadata. We need to re-read the `eia_860m.py` adapter to see how the signal is structured.

**Decision:** Before implementing, I need to verify the signal structure. If `value_text` carries the planned year, we can parse it. If not, the simplest fix is to add a `metadata` JSON field to `RawSignal` and `Signal` model. That's a schema change (alembic migration). This is high-risk for M2. 

**Alternative (simpler, still correct):** The recompute job already passes `since = now - _LOOKBACK_DAYS` and `until = now`. The EIA 860M adapter only emits planned additions for the current month (or recent months). In practice, the 860M XLSX is a monthly release with a rolling ~24-month forward horizon. So the 730-day lookback is over-filtering, not under-filtering — the adapter naturally limits to ~24 months. The real bug is if a historical 860M release (e.g. cached from 2 years ago) is still in the DB. Since there's no signal deduplication (idempotent insert), old 860M entries accumulate.

**Simpler fix:** In `_power_tightness`, drop signals where `observed_at < now - 180 days` (6 months) for planned_capacity_mw, because any 860M signal older than 6 months is stale forward-planning. This is a heuristic but correct: EIA 860M is a rolling monthly update.

Actually, let me reconsider. The `eia_860m.py` adapter caches by release month (`data/cache/eia860m/YYYY-MM.xlsx`), and each run re-ingests the current month. The `signals` table has no unique constraint, so every run appends new rows. Old planned additions from previous months remain in the table. The `_power_tightness` summing all of them means it counts each planned addition multiple times (once per ingestion run).

**The real fix:** Filter `planned_capacity_mw` to the latest `observed_at` per generator/plant, or the latest `observed_at` globally. The simplest: in `_power_tightness`, only consider signals where `observed_at` is within the last 90 days. This captures the most recent 860M release and ignores stale data.

Let me verify by reading `eia_860m.py` and `recompute_scores.py` to see how signals are filtered.

Actually, re-reading `recompute_scores.py:166-168`:
```python
.where(Signal.observed_at >= since.date())
.where(Signal.observed_at <= until.date())
```
Since `until = now` (the recompute timestamp), this filters to `observed_at <= now`. The 860M signals have `observed_at = date of the XLSX release` (or the month they represent). So if the adapter ran monthly for 2 years, there are 24 copies of the same planned addition in the DB, all with `observed_at` from the last 24 months. Summing them all means we count each planned addition 24 times. This is a serious bug.

**Correct fix:** `_power_tightness` should only consider the MOST RECENT signal per (segment, signal_name, source_id) within the lookback window. Or simpler: the recompute job should deduplicate signals by taking the latest `observed_at` per (segment, signal_name, source_id) before passing to extractors.

**Steps (revised):**
1. In `_load_signals_by_segment`, after fetching from the DB, deduplicate by taking the latest `observed_at` per (segment, signal_name, source_id) before grouping into `_SignalRow`.
2. Add test in `test_score_extractors.py`: create two signals with same source_id but different observed_at; assert only the latest is used.

### 4.2 Add orchestrator multi-adapter sequence test

**What:** No test asserts that an EIA failure doesn't block a FRED run.

**Spec:**
- Input: orchestrator with 2 adapters; adapter A raises on `fetch()`.
- Output: adapter B still runs; adapter A is marked ERROR; adapter B is marked SUCCESS.
- Verify: `test_refresh_daily.py` (new or existing) asserts both states are present in the run report.

**Steps:**
1. In `test_refresh_daily.py`, add a test that patches `build_eia_v2_adapter().fetch()` to raise `RuntimeError`.
2. Run the orchestrator with a minimal mock.
3. Assert `run_report["sources"]` contains `{"eia_v2": "ERROR", "fred": "SUCCESS"}`.

### 4.3 Unify refresh log path with launchd log

**What:** The orchestrator logs to `data/cache/refresh.log` but the launchd plist redirects to `data/cache/launchd.log`. Two logs for one job.

**Spec:**
- Input: `com.bottlewatch.refresh.plist` redirects to `launchd.log`.
- Output: Redirect to `refresh.log` (same as the orchestrator's JSONL log).
- Verify: `cat launchd/com.bottlewatch.refresh.plist | grep refresh.log`.

**Status (2026-06-06):** All three Phase 4 items done.

- 4.1 — ✅ **Implemented 2026-06-06.** The plan's diagnosis (filter `observed_at <= now - 180d`) was wrong for 860M: `observed_at` is the planned operation date, not the ingestion date, so the filter would be a no-op. The real bug is that the dedup in `recompute_scores._load_signals_by_segment` orders by `observed_at DESC` but does not include `ingested_at` in the sort — ties between ingestion runs of the same planned addition are broken arbitrarily. **Fix:** add `ingested_at` to the SELECT and change ORDER BY to `observed_at DESC, ingested_at DESC`. The docstring at `recompute_scores.py:152` was updated to clarify that 860M's "most recent" tie-breaker is `ingested_at`, not `observed_at`. **Tests:** new file `test_recompute_dedup.py` with 4 tests (n ingestions / single / non-idempotent / mix).
- 4.2 — ✅ Already done. `test_refresh_daily.py:211` `test_orchestrator_runs_independent_adapters_in_sequence` mocks EIA returning 400 and FRED returning a valid 2-point response, asserts `eia_v2.status == "ERROR"` and `fred.status == "OK"`, and that `fred.rows_written > 0`.
- 4.3 — ✅ Already done. Both `launchd/com.bottlewatch.refresh.plist` and `launchd/com.bottlewatch.recompute.plist` point to `data/cache/refresh.log` (not `launchd.log`).

---

## Phase 5: Frontend polish

### 5.1 Centralize regime colors, fix duplicate `ApiEdge` interface

**What:** `RegimeBadge.tsx`, `tickers/[ticker]/page.tsx:10-18`, and `tickers/page.tsx` all have identical `REGIME_COLORS` maps. `map/page.tsx:14-19` declares an `ApiEdge` interface that duplicates `chainLayout.ts`'s `ChainEdge`.

**Spec:**
- Input: 3+ copies of `REGIME_COLORS` and 2 copies of edge shape interface.
- Output: One `REGIME_COLORS` export in `frontend/app/lib/colors.ts`; one `ApiEdge` type in `frontend/app/lib/api.ts` or `chainLayout.ts`.
- Verify: `grep -r "REGIME_COLORS" frontend/app/` shows only import sites, no definitions.

**Steps:**
1. Create `frontend/app/lib/colors.ts` with `REGIME_COLORS` and `regimeColor(regime: string)`.
2. Replace all inline definitions with imports.
3. Move `ApiEdge` to `chainLayout.ts` or `api.ts` as an exported type.
4. Remove the inline declaration from `map/page.tsx`.

### 5.2 Fix TipTap plain-text storage

**What:** `thesis/page.tsx` stores `body_md = editor.getText()` — plain text, not markdown, so bold/italic/lists are dropped. The docstring claims TipTip serializes via markdown extension, but no markdown extension is imported.

**Spec:**
- Input: TipTap editor with bold text.
- Output: `body_md` contains `**bold**` markdown.
- Verify: Add `@tiptap/extension-markdown` or use `editor.getHTML()` → convert HTML to MD, or use `editor.storage` to get a markdown representation. Simpler: install `@tiptap/extension-markdown` and call `editor.storage.markdown.getMarkdown()`.

**Steps:**
1. Add `@tiptap/extension-markdown` to `frontend/package.json`.
2. In `thesis/page.tsx`, replace `editor.getText()` with `editor.storage.markdown.getMarkdown()`.
3. Update the POST payload type accordingly.

### 5.3 Scoreboard sparkline N+1 fix

**What:** `ScoreboardTable.tsx` renders one `SparklineForSegment` per row, each making an independent `getScoreHistory` call. For 10 segments that's 10 round-trips.

**Spec:**
- Input: 10 rows, each with its own `useEffect` fetching score history.
- Output: One batch fetch of all score histories, or the score history is included in the initial `/scores/regime` response.
- Verify: `ScoreboardTable` renders with 1 API call instead of 10.

**Steps:**
1. Add `/api/v1/scores/history?segments=seg1,seg2,...` endpoint (or include history in the existing `/scores/regime` response via an optional `?include_history=true` query param).
2. Update `ScoreboardTable` to use the batched data.
3. This is M3 work; the plan already has this in the backlog. Mark as "optional M3 enhancement, not blocking".

**Status (2026-06-06):** All three Phase 5 items done.

- 5.1 — ✅ Already done. No duplicate `REGIME_COLORS` definitions in `components/RegimeBadge.tsx`, `tickers/page.tsx`, `tickers/[ticker]/page.tsx`, or `map/page.tsx` (grep returns one definition site + import sites). `ApiEdge` is exported from `chainLayout.ts`.
- 5.2 — ✅ Already done. `thesis/page.tsx` uses a custom ProseMirror JSON → markdown serializer (~40 lines) rather than pulling in `@tiptap/extension-markdown`. The serializer is inlined at the top of the file with a comment explaining the trade-off.
- 5.3 — ✅ **Implemented 2026-06-06.** Backend: extended `GET /api/v1/scores/history` to accept `?segments=a,b,c` (batched) alongside the existing `?segment=X` (single); the two are mutually exclusive (400 on both, 400 on `segments=` empty, 422 from FastAPI if neither given). Response shape: `{horizon, months, series: [{segment, points: []}, ...]}` in request order, with `points: []` for unknown or empty segments. **Frontend:** new hook `useBatchedScoreHistory` in `components/SparklineForSegments.tsx` issues one `getScoreHistoryBatched` call and returns a `Map<segment, points>`. `ScoreboardTable` uses the hook once at the table level and renders the dumb `<Sparkline>` per row, looking up its points in the map. The previous per-row `SparklineForSegment` fetcher is unchanged and still used by `/tickers/[ticker]` (where only one row is rendered). **Tests:** 7 new backend tests in `test_api_scores_history.py` (batched response shape, mutual exclusion, empty segments, unknown segment, single-segment backward compat, batched requires horizon, batched unknown horizon); 4 new frontend tests in `SparklineForSegments.test.tsx` (single fetch for N segments, Map keyed by slug, no refetch on re-render with same args, empty list). **New frontend infra:** vitest 2.1.9, @testing-library/react 16.3.2, jsdom 25, @testing-library/jest-dom 6.9.1, `vitest.config.ts`, `vitest.setup.ts`, `pnpm test` script.

---

## Phase 6: Operability

### 6.1 Template launchd plist path

**What:** `com.bottlewatch.refresh.plist:11` hard-codes `/Users/iljoyoo/workspace/bottlewatch`.

**Spec:**
- Input: plist with hardcoded path.
- Output: `install.sh` reads `PWD` or a `BOTTLEWATCH_ROOT` env var and templates the plist before copying to `~/Library/LaunchAgents/`.
- Verify: Run `install.sh` from a different directory; plist contains the correct path.

**Steps:**
1. In `install.sh`, replace the hardcoded path with a `sed` substitution using `$(cd .. && pwd)` or the script's own directory resolution.
2. Update `uninstall.sh` similarly.

### 6.2 Add model-migration drift check

**What:** No way to detect if a developer changes a model and forgets to add an alembic migration.

**Spec:**
- Input: ORM model changed; no new alembic migration.
- Output: `make check-migrations` (or a CI step) runs `alembic check` (or `alembic revision --autogenerate --dry-run`) and fails if drift is detected.
- Verify: Change `models.py`, run the check, it fails.

**Steps:**
1. Add `check-migrations` to Makefile.
2. Use `alembic revision --autogenerate -m "drift-check"` and assert no diff is generated, then remove the generated revision.

### 6.3 Move static ETA / series spec / states to config files

**What:** `_STATIC_ETA` in `app/api/eta.py:34-46`, `_SERIES_SPEC` in `eia.py:63-81`, `_STATES` in `eia_capacity.py:56-108` are hardcoded Python dicts.

**Spec:**
- Input: hardcoded constants in Python modules.
- Output: JSON config files under `data/config/` or `research/` loaded at import time.
- Verify: Changing the JSON changes the output without editing source.

**Steps:**
1. Create `research/config/eta.json`, `eia_series_spec.json`, `eia_states.json`.
2. Load them at module import time with `json.loads(Path(...).read_text())`.
3. Add tests that assert the JSON round-trips.

**Status (2026-06-06):** All three Phase 6 items done.

- 6.1 — ✅ Already done. `launchd/install.sh` reads `BOTTLEWATCH_ROOT` (defaulting to the script's parent dir) and pipes the source plist through `sed` to substitute the install-time root. `uninstall.sh` reverses the substitution back to the default `/Users/iljoyoo/workspace/bottlewatch` on cleanup. Both plists in the repo retain the canonical default path.
- 6.2 — ✅ Already done. `make check-migrations` runs `alembic revision --autogenerate` with a timestamped `rev-id`, asserts the generated migration is empty (the `pass` line + zero `op.*` calls), and removes it.
- 6.3 — ✅ Already done. `research/config/eta.json`, `research/config/eia_series_spec.json`, and `research/config/eia_states.json` all exist. `app/config_loader.py` provides `load_eta_table`, `load_eia_series_spec`, and `load_eia_states`; `_STATIC_ETA` in `eta.py:39`, `_SERIES_SPEC` in `eia.py:67`, and `_STATES` in `eia_capacity.py:59` all read from JSON at import time. `test_config_loader.py` covers all three.

---

## Phase 7: One end-to-end integration test

### 7.1 Add user-journey end-to-end test

**What:** No single test covers ingest → recompute → API → ticker detail. The highest-leverage test that would catch multiple bugs at once.

**Spec:**
- Input: mocked network, clean in-memory DB.
- Steps:
  1. `refresh_daily` runs with mocked EIA and FRED adapters.
  2. `recompute_scores` runs.
  3. `GET /api/v1/segments` returns 10 segments with regimes.
  4. `GET /api/v1/map` returns the value chain.
  5. `GET /api/v1/tickers/HUBB` returns non-empty `companies`.
  6. `GET /api/v1/scores/regime` returns rows with `data_completeness > 0`.
- Verify: All assertions pass.

**Steps:**
1. Create `test_end_to_end.py` in `src/bottlewatch/tests/`.
2. Use the existing `conftest.py` fixtures (`seeded_factory`, `client`).
3. Use `respx` to mock EIA and FRED network calls.
4. Run `refresh_daily` orchestrator → `recompute_scores` → HTTP GETs.
5. Assert HUBB's `companies` is non-empty (catches slug bug).
6. Assert no stub-adapter signals are in DB (catches stub registry bug).
7. Assert `transformers_tnd` score > 0 with FRED signal (catches FRED signal flow).

**Status (2026-06-06):** ✅ Already done. `test_end_to_end.py` exists with the exact assertions the plan called for: stub-source rows == 0 in DB after `refresh_daily` (line 124-129), HUBB's `companies` is non-empty (line 164-165), and the file is a 173-line end-to-end journey.

---

## Execution order

| Phase | Items | Risk | Dependencies |
|---|---|---|---|
| 1 | 1.1–1.3 | Low | None |
| 2 | 2.1–2.5 | Low | None |
| 3 | 3.1–3.2 | Medium | None |
| 4 | 4.1–4.3 | Medium | 2.1 (shared module pattern) |
| 5 | 5.1–5.3 | Low | None |
| 6 | 6.1–6.3 | Low | None |
| 7 | 7.1 | Low | All above (for maximum coverage) |

Phases 1 and 2 are independent and can be done in parallel. Phase 3 depends on nothing. Phase 4's deduplication fix is the most technically interesting. Phases 5–6 are frontend/ops polish. Phase 7 is the capstone.

---

## Verification

After each phase, run:
```bash
make research    # ontology + validation still works
make test        # 80% coverage threshold still passes
make ingest      # dry-run: no stub signals in DB
make recompute   # dry-run: scores computed
make api         # FastAPI boots
make web         # Next.js boots
```

---

## Questions for the user

1. **Key rotation:** ~~Do you want to rotate the EIA/FRED/Comtrade/Postgres keys now, or just remove `.env` and defer rotation to when you're ready?~~ **Resolved 2026-06-06:** Operator chose to keep `.env` (no rotation); see 1.1 above.
2. **Regime threshold calibration:** ~~Should the code's (70, ±20/0/±30/-15) be the canonical source of truth, or do you want to revert to the plan's (60, ±5)?~~ **Resolved 2026-06-06:** Code's (70, ±20/0/±30/-15) is canonical. The (60, ±5) was explicitly called a placeholder in the v1 plan §7.2; the JSON file is the single source of truth and the plan is annotated to point at it. See 3.1.
3. **Stub adapters:** ~~Should they be completely removed from the registry (not just `is_configured=False`), or is `SKIP` with a clear message acceptable?~~ **Resolved 2026-06-06:** SKIP with a clear message. The orchestrator's `SKIPPED (not yet implemented in M3)` line is the operator-visible contract; the adapter files stay in the codebase as the v1.1 stubs. See 2.2.
4. **End-to-end test scope:** ~~Should the E2E test cover the full frontend render (e.g. with Playwright), or is backend-only (ingest → recompute → API calls) sufficient for M2?~~ **Resolved 2026-06-06:** Backend-only. The current `test_end_to_end.py` covers ingest → recompute → API; full-frontend render tests (Playwright) are deferred to M3+. See 7.1.

---

## Final status (closed 2026-06-06)

All 17 items across Phases 1–7 closed. Of those:

- **13 were already done in the codebase** when this plan was reviewed (1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 4.2, 4.3, 5.1, 5.2, 6.1, 6.2, 6.3, 7.1) — the plan was significantly stale.
- **2 were implemented during this work** (4.1, 5.3). 4.1 was the technically interesting backend fix (dedup tie-breaker); 5.3 was the frontend N+1 fix and brought in vitest + RTL.
- **2 were resolved by operator decision rather than code change** (1.1 — keep `.env`; 1.3 — pre-commit hook was already in place).

**Verification ran (2026-06-06):**

| Step | Command | Result |
|---|---|---|
| Ontology + validate | `make research` | 4/4 PASS (reasoner, class consistency, companies have ticker, geo/supply_path/NVDA mates) |
| Tests with coverage gate | `make test` | 272 passed, 5 skipped, 0 failed. Coverage 86.46% > 80% threshold. |
| Frontend build | `pnpm build` | 7 routes generated, no TypeScript errors. |
| Frontend tests | `pnpm test` | 4/4 vitest tests pass. |

**Net code changes during this work:**

- `src/bottlewatch/jobs/recompute_scores.py` — `+2/-1` lines (added `ingested_at` to SELECT and ORDER BY); docstring expanded.
- `src/bottlewatch/app/api/scores.py` — refactored: extracted `_history_rows_for` helper, added `segments` batched mode (mutually exclusive with `segment`).
- `src/bottlewatch/tests/test_recompute_dedup.py` — **new**, 4 tests.
- `src/bottlewatch/tests/test_api_scores_history.py` — `+97` lines, 7 new tests for batched mode.
- `frontend/app/lib/api.ts` — added `ScoreHistoryBatched` type and `getScoreHistoryBatched` fetcher.
- `frontend/app/components/SparklineForSegments.tsx` — **new**, `useBatchedScoreHistory` hook.
- `frontend/app/components/SparklineForSegments.test.tsx` — **new**, 4 tests.
- `frontend/app/components/ScoreboardTable.tsx` — replaced per-row `SparklineForSegment` with batched hook + dumb `<Sparkline>`.
- `frontend/vitest.config.ts` — **new**.
- `frontend/vitest.setup.ts` — **new**.
- `frontend/package.json` — added `test` and `test:watch` scripts; devDeps: vitest, @testing-library/react, @testing-library/jest-dom, jsdom.
