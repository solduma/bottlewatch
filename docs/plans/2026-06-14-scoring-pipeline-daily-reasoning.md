# Plan: Daily Scoring Refresh + Research Re-Reasoning

**Date:** 2026-06-14
**Scope:** Three workstreams:
1. Fix the EIA-860M future-date filtering bug so `power_generation_oem.capacity_tightness` actually uses planned additions.
2. Broaden dynamic extractor coverage so daily recomputes move more than a handful of segments.
3. Add a daily "research re-reasoning" step that audits seed values against live signals and produces human-reviewable rationales.

---

## 1. Decision points for the user

Before implementation starts, three choices affect the design:

| # | Question | Option A (recommended) | Option B |
|---|---|---|---|
| 1 | **EIA-860M semantics** | Keep `observed_at` as the planned operation date; make the scoring window future-aware for planned capacity only. | Change `observed_at` to the 860M publication date and store planned year/month in `source_id`/`value_text`. |
| 2 | **Re-reasoning depth** | **Daily rationales only:** generate a markdown delta per segment, flag divergences, but do NOT auto-edit `scoring_seed.json`. | **Auto-update seeds:** let an LLM propose new seed values and write them to `scoring_seed.json` automatically. |
| 3 | **LLM provider** | Anthropic Claude (consistent with Claude Code stack). | OpenAI / local model. |

**My recommendation:** Option A for all three. It preserves clean semantics, keeps humans in the loop for seed edits, and uses the model already wired into the project's workflow.

---

## 2. Workstream A: EIA-860M date-filter fix

### 2.1 Problem

`eia_860m.py` sets `observed_at` to the generator's **planned operation year-month** (e.g. `2027-01-01`).

`recompute_scores.py:_load_signals_by_segment()` loads signals where `observed_at <= naive_now`. All future planned additions are dropped before `_power_tightness()` sees them.

So `power_generation_oem.capacity_tightness` is computed almost entirely from past/operating data, producing a downward-biased score.

### 2.2 Recommended fix: future-aware window for planned capacity

Keep the planned-operation semantics. Extend the signal load window to include future planned capacity up to 36 months ahead **only for `planned_capacity_mw`**.

### 2.3 Spec

**Inputs/outputs:**
- Input: `signals` table rows with `signal_name="planned_capacity_mw"` and `observed_at` in `[now - 730d, now + 1095d]`.
- Output: these rows are included in `signals_by_segment["power_generation_oem"]` fed to `extractors.capacity_tightness()`.
- Non-planned signals continue to use `[now - 730d, now]`.

**Behavioral contract:**
- The recompute job must not accidentally load all future signals for all signal names.
- The dedup logic (`_IDEMPOTENT_SOURCES`) must still apply.
- If no future planned capacity exists, the extractor falls back to existing behavior (None or past-only).

**Error modes:**
- A malformed `observed_at` in the future is dropped by the existing `_to_date` handling.
- 860M fetch failure is already handled by the refresh job; recompute just sees fewer signals.

**Testable properties:**
- A fixture signal with `observed_at = today + 365 days` and `signal_name="planned_capacity_mw"` is included in the recompute.
- A fixture signal with `observed_at = today + 365 days` and `signal_name="capacity_mw"` is excluded.
- `_power_tightness()` returns the expected ratio when future planned capacity is present.

### 2.4 Implementation steps

1. In `recompute_scores.py`, split the signal query into two windows:
   - Window 1 (all signals): `observed_at >= since` and `observed_at <= naive_now`.
   - Window 2 (planned capacity only): `signal_name="planned_capacity_mw"`, `observed_at >= since`, `observed_at <= naive_now + 1095d`.
2. Merge the two result sets, keeping the dedup logic intact.
3. Add unit/integration tests in `test_recompute_scores.py`.
4. Update the docstring in `recompute_scores.py` to document the future window.

### 2.5 Alternative: change `observed_at` semantics

If Option B is preferred:
- Change `eia_860m.py:_row_to_signal()` to set `observed_at` to the 860M release date.
- Encode planned year/month into `source_id` or a new metadata column.
- Requires a migration or at least a signal-schema change.

**Why I recommend Option A:** it keeps `observed_at` as the thing that actually happened (planned operation date), and the scoring window is the pipeline's concern. It also avoids schema changes.

---

## 3. Workstream B: Broader dynamic extractor coverage

### 3.1 Current state

Only 3 segments have dynamic `capacity_tightness`, and only `transformers_tnd` has dynamic `lead_time_growth` and `demand_signal`:

| Segment | Dynamic sub-scores | Source |
|---|---|---|
| `power_generation_oem` | `capacity_tightness` | EIA 860M + EIA capacity |
| `data_center_shell` | `capacity_tightness` | EIA TX retail sales (weak proxy) |
| `transformers_tnd` | `capacity_tightness`, `lead_time_growth`, `demand_signal` | FRED WPU1321, A35SNO |

All other segments use static seed values for 4 of 5 sub-scores.

### 3.2 Goal

Make daily recomputes meaningfully dynamic for at least the **original 10 segments** by the end of this work, and lay the groundwork for the rest.

### 3.3 Proposed additions (phased)

#### Phase 1: Use existing FRED series as cross-segment proxies

| FRED series | Signal name | Can proxy for | Sub-score mapping |
|---|---|---|---|
| `WPU31132506` | `ppi_semis` | Semi segments (`advanced_node_fabs`, `hbm_memory`, `gpu_asic_silicon`, `networking_interconnect`, `advanced_packaging`) | `lead_time_growth` |
| `INDPRO` | `industrial_production` | Manufacturing/utility segments | `demand_signal` |
| `TCU` | `capacity_utilization` | Manufacturing/utility segments | `capacity_tightness` |

*Note: these are noisy cross-segment proxies. They should be overrides that fall back to seeds when signals are missing.*

#### Phase 2: SEC EDGAR keyword extraction

`sec_edgar.py` already fetches 10-K/10-Q text. Add a simple keyword-count extractor that maps filings to segments and computes:
- `lead_time_growth` proxy: mentions of "lead time", "backlog", "allocation", "slot".
- `capacity_tightness` proxy: mentions of "book-to-bill", "order book", "sold out", "nameplate capacity".

This needs a mapping from company ticker → segment(s) from `02_universe.csv`.

#### Phase 3: Better data-center demand proxy

Replace or supplement ERCOT residential sales with a hyperscaler capex aggregate derived from SEC EDGAR 10-Q/8-K.

### 3.4 Spec for Phase 1 (this plan's scope)

**Inputs/outputs:**
- Input: FRED signals already ingested into `signals` table.
- Output: dynamic sub-score overrides passed into `compute_segment_score()` for eligible segments.

**Behavioral contract:**
- A segment's dynamic override only fires when the right signal is present and has enough history.
- When the dynamic override is `None`, the research seed is used (existing behavior).
- Dynamic values are clamped to `[0, 1]` by the extractor.

**Testable properties:**
- `advanced_node_fabs.lead_time_growth` uses `ppi_semis` when signals exist.
- `advanced_node_fabs.lead_time_growth` falls back to seed when no `ppi_semis` signals exist.
- Other segments' sub-scores are unaffected.

### 3.5 Implementation steps

1. In `fred.py`, confirm `WPU31132506` / `INDPRO` / `TCU` series are registered and ingested (they already are, but verify mapping).
2. In `extractors.py`, add dispatch functions:
   - `lead_time_growth_for_semis(signals)` using `ppi_semis` YoY or level.
   - `demand_signal_for_manufacturing(signals)` using `industrial_production` YoY.
   - `capacity_tightness_for_manufacturing(signals)` using `capacity_utilization` deviation from LR mean.
3. Update `capacity_tightness()`, `demand_signal()`, and `lead_time_growth()` dispatchers to route the right segments to the new extractors.
4. In `recompute_scores.py`, pre-compute these overrides segment-by-segment, same pattern as existing `demand_signal_by_segment` and `lead_time_by_segment`.
5. Add tests in `test_score_extractors.py` and `test_recompute_scores.py`.

### 3.6 Out of scope for this plan

- Paid data sources (SEMI WFF, Wood Mackenzie, TrendForce).
- Real-time web scraping of trade press.
- Ticker-level (rather than segment-level) signals.

---

## 4. Workstream C: Daily re-reasoning of research

### 4.1 What it means

"Re-reasoning" has two concrete parts:

1. **Divergence audit:** For every segment, compare the latest dynamic sub-score (from signals) against the static research seed. If the gap is large (>0.2), flag it.
2. **Daily rationale generation:** Produce a short markdown rationale per segment explaining the current score, the biggest movers since yesterday, and any seed/dynamic divergence.

The output is human-reviewable, stored in `research/daily/<date>/`, and optionally surfaced in the API/frontend.

### 4.2 Recommendation: rationales + flags, no auto-edit

Do not let an LLM overwrite `scoring_seed.json` without human review. Instead:
- Generate a daily `reasoning.jsonl` / `reasoning.md` artifact.
- Flag divergences in the API under a new `/api/v1/research/daily` endpoint.
- A maintainer reviews the artifact and manually updates seeds when convinced.

This keeps the research seed as the authoritative human-curated value while making the daily reasoning visible.

### 4.3 Spec

**Inputs:**
- Latest `scores` table rows (sub_scores, B, B', regime).
- Latest `signals` table rows for each segment.
- Prior day's `scores` (for delta).
- `scoring_seed.json` values.

**Outputs:**
- `research/daily/YYYY-MM-DD/reasoning.md` — per-segment rationale.
- `research/daily/YYYY-MM-DD/divergences.json` — structured divergence flags.
- New DB table `research_snapshots` (optional but recommended) storing the same content for API access.

**Behavioral contract:**
- The job runs after `bottlewatch-recompute` succeeds.
- It only calls the LLM for segments with non-trivial changes (B' magnitude > 5, new signal data, or divergence > 0.2). Otherwise it copies/extends the previous rationale.
- Each rationale cites specific signals and seed values; it does not invent data.
- Divergence flags identify which sub-score diverged, by how much, and why it matters.

**Error modes:**
- LLM API key missing → job logs warning and writes a minimal machine-generated rationale (no LLM prose).
- LLM rate-limit → retry with backoff; if all fail, fall back to machine-generated rationale.
- Segment not in seed → skip with warning.

**Testable properties:**
- A segment with a large seed-vs-dynamic divergence gets a `divergence` entry.
- A segment with unchanged scores and no new signals is either skipped or produces a stable rationale.
- The generated rationale references real signal names from the `signals` table.

### 4.4 New model / DB surface

```python
class ResearchSnapshot(Base):
    __tablename__ = "research_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    segment: Mapped[str] = mapped_column(String, nullable=False)
    horizon: Mapped[str] = mapped_column(String, nullable=False)  # "near" | "med" | "long" | "all"
    date: Mapped[date] = mapped_column(Date, nullable=False)
    rationale_md: Mapped[str] = mapped_column(Text, nullable=False)
    divergences: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    generated_by: Mapped[str] = mapped_column(String, nullable=False)  # "llm" | "machine"
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
```

API endpoint: `GET /api/v1/research/daily?segment=<slug>&date=<YYYY-MM-DD>`.

### 4.5 Implementation steps

1. Add `ANTHROPIC_API_KEY` to `Settings` (`config.py`) and `.env` template.
2. Add `ResearchSnapshot` model + alembic migration.
3. Create `src/bottlewatch/jobs/research_daily.py` with:
   - `_build_prompt(segment, score_rows, signal_rows, seed_values, prev_reasoning)`
   - `_call_llm(prompt)` using Anthropic Messages API.
   - `_machine_fallback(...)` for the no-LLM case.
   - `run()` that iterates segments, generates/upserts snapshots, writes artifacts.
4. Add `bottlewatch-research` CLI entry in `pyproject.toml`.
5. Add API router `src/bottlewatch/app/api/research.py` with the daily endpoint.
6. Register router in `app/main.py`.
7. Add tests:
   - `test_research_daily.py` — mock LLM response, assert snapshot is written.
   - `test_api_research.py` — GET endpoint returns snapshot.
8. Update `launchd` with a third agent or combine into the recompute agent: after recompute, run `bottlewatch-research`.

### 4.6 Prompt structure (sketch)

```
You are a research analyst for Bottlewatch, a dashboard that scores
AI-supply-chain bottlenecks. Given the segment, today's sub-scores,
yesterday's sub-scores, and the latest raw signals, produce a 3-sentence
rationale in Markdown:

1. What is the current regime and why?
2. Which sub-score moved the most since yesterday, and what signal drove it?
3. Is any dynamic signal diverging from the research seed? If so, flag it.

Be concise. Cite specific signal names and values. Do not invent data.
```

Output schema:
```json
{
  "rationale_md": "string",
  "divergences": [
    {"sub_score": "lead_time_growth", "seed": 0.85, "dynamic": 0.63, "gap": -0.22}
  ]
}
```

---

## 5. Integration / scheduling

### 5.1 Recommended job order

The daily pipeline should run as a single ordered sequence:

```
04:00  bottlewatch-refresh   (fetch signals)
04:30  bottlewatch-recompute (rebuild scores, fix EIA-860M window)
04:35  bottlewatch-research  (generate rationales, divergence audit)
```

### 5.2 launchd options

| Approach | Pros | Cons |
|---|---|---|
| **Three separate agents** (add `com.bottlewatch.research.plist`) | Simple, mirrors existing pattern | Recompute may run on stale data if refresh fails; research may run on stale scores if recompute fails. |
| **One wrapper script** that runs all three sequentially with exit-code checks | Guarantees ordering and skip-on-failure | One plist to maintain; need to handle partial failure. |

**Recommendation:** one wrapper script `launchd/com.bottlewatch.daily.plist` running a new `make daily` target:

```makefile
daily:
	uv run bottlewatch-refresh && \
	uv run bottlewatch-recompute && \
	uv run bottlewatch-research
```

Deprecate the separate refresh/recompute plists, or keep them but schedule the wrapper at a different time.

### 5.3 Make targets

Add:
- `make daily` — runs refresh → recompute → research.
- `make research` — runs `bottlewatch-research` alone.

Keep existing `make ingest` and `make recompute` for ad-hoc use.

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| LLM costs grow with segment count | Only call LLM for changed segments; batch segments into one prompt if API supports it. |
| FRED/SEC signals are noisy cross-segment proxies | Document clearly in `research/04_scoring_methodology.md` that these are M2 proxies, not primary sources. |
| EIA-860M future window accidentally includes stale old planned capacity that already commissioned | The 730-day lookback + dedup by `source_id` handles this; completed projects drop out naturally as `observed_at` ages. |
| Research snapshots bloat the DB | Retain only the last 90 days in DB; full history stays in `research/daily/` files. |
| Auto-generated rationales hallucinate | Enforce structured JSON output, cite only provided signal names, and use machine fallback when LLM is unavailable. |

---

## 7. Files to touch

| File | Change |
|---|---|
| `src/bottlewatch/jobs/recompute_scores.py` | Future-aware signal window for `planned_capacity_mw`; pre-compute new dynamic overrides. |
| `src/bottlewatch/app/score/extractors.py` | Add cross-segment FRED extractors. |
| `src/bottlewatch/app/score/formula.py` | No change expected if overrides already wired; verify. |
| `src/bottlewatch/config.py` | Add `anthropic_api_key`. |
| `src/bottlewatch/app/db/models.py` | Add `ResearchSnapshot`. |
| `alembic/versions/` | New migration for `research_snapshots`. |
| `src/bottlewatch/jobs/research_daily.py` | New daily reasoning job. |
| `src/bottlewatch/app/api/research.py` | New API router. |
| `src/bottlewatch/app/main.py` | Register research router. |
| `pyproject.toml` | Add `bottlewatch-research` script; add `anthropic` dependency. |
| `Makefile` | Add `daily` and `research` targets. |
| `launchd/` | Add unified daily plist (and optionally remove old separate plists). |
| `src/bottlewatch/tests/test_recompute_scores.py` | EIA-860M future-window test; new extractor tests. |
| `src/bottlewatch/tests/test_score_extractors.py` | Cross-segment FRED extractor tests. |
| `src/bottlewatch/tests/test_research_daily.py` | New. |
| `src/bottlewatch/tests/test_api_research.py` | New. |
| `research/04_scoring_methodology.md` | Document new proxies and daily reasoning artifact. |

---

## 8. Suggested implementation order

1. **EIA-860M fix** — smallest change, highest correctness impact.
2. **Phase 1 dynamic extractors** — extends existing pattern.
3. **Research snapshot model + migration** — backend plumbing.
4. **Daily reasoning job + API** — new capability.
5. **launchd unification + Makefile targets** — operationalize.
6. **Full test suite + docs update** — ship.

---

## 9. Open questions

1. Do you want the EIA-860M fix to preserve `observed_at` semantics (recommended) or republish to the release date?
2. Do you want daily re-reasoning to auto-edit `scoring_seed.json` or only produce reviewable rationales/diffs?
3. Are you comfortable adding `anthropic` as a dependency and an `ANTHROPIC_API_KEY` env var?
4. Should Phase 1 extractors apply to **all** semi segments, or only the original 10?
5. Should old separate launchd agents be removed, or should the new unified agent coexist with them?
