# Plan: Add progress bar to `make ingest`

**Date:** 2026-06-09
**Scope:** Orchestrator (`refresh_daily.py`) + sec_insider adapter + Protocol touch

---

## Problem

`make ingest` (→ `bottlewatch-refresh`) is currently a silent black hole for the ~90s that `sec_insider` runs. The orchestrator loops over ~9 adapters; the first ~8 are SKIPPED (watermark fresh) in <1s, then `sec_insider` iterates over 98 tickers at 5 req/sec + sleep. The user can't tell if the process is hung or working.

## Goal

A single-line progress indicator on stderr that shows:
1. **Outer progress:** which adapter is running ("eia_v2: SKIPPED", "sec_insider: 47/98").
2. **Inner progress:** for the long-running adapter (`sec_insider`), which ticker is being processed.
3. **Elapsing time** so the user can estimate total runtime.

When stderr is NOT a TTY (cron, launchd, pipe redirect), the progress bar is a silent no-op — no garbage in logs.

---

## Design

### 1. Simple `\r`-based progress (no new dependency)

A `Progress` class (~40 lines) in `refresh_daily.py`:
- `update(stage, current, total, message)` — writes a `\r`-terminated line to stderr.
- `done()` — clears the line, writes newline.
- No-op if `not sys.stderr.isatty()`.

Why not tqdm/rich? The project uses stdlib-first. A 40-line utility is cheaper than a new dependency.

### 2. Optional `progress` callback on `Adapter.fetch()`

```python
# base.py — backward-compatible Protocol change
def fetch(
    self, period_start: date, period_end: date,
    progress: Callable[[int, int, str], None] | None = None,
) -> list[RawSignal]: ...
```

- All 8 other adapters accept `progress=None` and ignore it.
- `sec_insider` calls `progress(i, total, ticker)` per ticker (line 157 loop).
- The orchestrator passes a `Progress.update()` wrapper as the callback.

**Why this approach:**
- No monkey-patching or stateful attributes on adapter instances.
- The callback is the "tell, don't ask" pattern — the adapter decides what granularity to report.
- Only the slow adapter (`sec_insider`) emits inner progress; others are silent.
- If a future adapter (e.g. EIA v2 with many series) becomes slow, it can opt-in by using the same callback.

### 3. Orchestrator changes

In `run()` (line 311), wrap the adapter loop with `Progress`:
```python
prog = Progress(len(registry))
for i, spec in enumerate(registry, 1):
    adapter = spec.factory(settings)
    prog.update(i, len(registry), spec.name, "starting...")
    result = _run_one(spec, adapter, factory, since, until, started, prog)
    # ...
prog.done()
```

`_run_one()` passes the progress callback to `adapter.fetch()` when it's a TTY:
```python
signals = adapter.fetch(period_start, period_end, progress=prog.inner_callback)
```

### 4. Test additions

- `test_refresh_daily.py`: `test_progress_bar_silent_on_non_tty` — mocks `sys.stderr.isatty = lambda: False`, asserts no stderr output.
- `test_sec_insider_adapter.py`: `test_fetch_calls_progress_callback_per_ticker` — passes a `MockProgress` to `adapter.fetch()` and asserts it's called ~98 times with `(i, total, ticker)`.

---

## Files touched

| File | Change |
|---|---|
| `src/bottlewatch/app/ingest/base.py` | Add `progress` param to `fetch()` Protocol signature |
| `src/bottlewatch/app/ingest/sec_insider.py` | Accept `progress` param, call it per ticker |
| `src/bottlewatch/app/ingest/*.py` (8 files) | Accept `progress=None` in `fetch()` signatures (no-op) |
| `src/bottlewatch/jobs/refresh_daily.py` | Add `Progress` class, wire it into the orchestrator loop |
| `src/bottlewatch/tests/test_refresh_daily.py` | Add TTY/non-TTY progress tests |
| `src/bottlewatch/tests/test_sec_insider_adapter.py` | Add progress-callback test |

---

## Verification

```bash
make test            # 309+ pass, coverage ≥ 80%
make ingest          # shows progress line on stderr
make ingest | cat    # silent (no TTY, no garbage)
```

---

## Simpler alternative considered (rejected)

**Option B: Monkey-patch `_progress` on the adapter instance.**
- No Protocol change.
- `sec_insider` checks `hasattr(self, '_progress')`.
- Rejected: monkey-patching is implicit and fragile; the callback approach is explicit and testable.

---

## Open question

Should the progress callback also support `message`-only updates for adapters that don't know their total count (e.g. EIA v2, which fetches series until exhaustion)? The current design uses `(current, total, label)` which is the 98-ticker case. For open-ended fetches we'd need a second callback shape. I propose we add `progress: Callable[[int, int, str], None] | None` now (closed-ended) and extend to `Callable[[str], None]` (message-only) later if a second slow adapter appears. Single-use flexibility is not needed today.

---

**Recommendation:** Implement Option A (callback + `Progress` class) as described. It's the minimum code that solves the problem, no new dependencies, no fragile monkey-patching, and the Protocol change is backward-compatible.
