# Spec: T2.2 — Validate LLM research output before persistence

**Date:** 2026-06-18
**Covers:** T2.2 from `2026-06-18-improvement-assessment.md`.
**Why spec-first:** LLM output is persisted as the official "research rationale"
and shown to an investor; hallucinated numbers are a trust/correctness risk.

**Provider note:** the LLM path is **Ollama** (`research_daily.py:279-325`,
OpenAI-compatible chat endpoint, default `llama3.2`). Not Claude/Anthropic — no
Anthropic SDK involved. This spec is provider-agnostic.

---

## Problem (verified against the code)

1. **No output validation.** `_generate_for_segment_horizon`
   (`research_daily.py:370-380`) takes whatever `_call_llm` returns and persists
   it verbatim as `rationale_md` (DB `ResearchSnapshot` + `reasoning.md`). The
   prompt says "Do not invent data" (`:276`) but nothing checks the claim. A
   hallucinated figure becomes an official rationale, indistinguishable from a
   real one except the `generated_by="llm"` tag.

2. **LLM failure is invisible in the run report.** On any exception, the code
   logs a warning and falls back to the machine rationale tagged
   `generated_by="machine"` (`:381-390`). The run report counts only `llm` vs
   `machine` (`:516-531`), so a persistent outage looks identical to "nothing was
   interesting today" — the operator can't tell a degraded run from a quiet one.

3. **The `reasoning`-field fallback persists chain-of-thought.** When `content`
   is empty, `_call_llm` returns the model's `reasoning` scratch-pad (`:319-324`)
   as the rationale. Honest but risky — raw reasoning isn't a vetted answer.

---

## Design

Two independent, cheap mechanisms. Neither calls the LLM again.

### A. Numeric-claim validation (anti-hallucination)

After `_call_llm` returns, before building the `llm` result, validate that the
**numbers** the rationale cites are grounded in the context the prompt was given.

- **Grounding set** = the numeric values actually available to the prompt:
  each signal's `value_num`, the score `B`, momentum `B'`, prev score, and the
  sub-score / seed / divergence values (seed, dynamic, gap). All floats the model
  was shown.
- **Extract** every number in the rationale text via a regex
  (`-?\d+(?:\.\d+)?`), ignoring obvious non-claims: integers ≤ a small bound that
  are sentence enumerators are NOT special-cased (keep it simple — see review),
  and percentages are matched on their numeric part.
- **Check**: each extracted number must match some grounding value within a
  tolerance (`abs(a-b) <= max(_ABS_TOL, _REL_TOL*|b|)`, e.g. abs 0.05, rel 2%) to
  allow rounding ("B=64.8" cited as "65"). A number with no match within
  tolerance is an **unverified claim**.
- **Policy** (config-driven constant `_MAX_UNVERIFIED_CLAIMS`, default 0): if the
  count of unverified numbers exceeds the threshold, **reject** the LLM rationale
  and fall back to the machine rationale, tagged `generated_by="machine_rejected"`
  with the reason logged. The rationale text is NOT persisted.

### B. Honest run accounting

- Extend `RationaleResult` with `generated_by` values:
  `"llm"` | `"machine"` (not interesting / no key) | `"machine_llm_error"` (LLM
  raised) | `"machine_rejected"` (validation failed). Existing `"machine"` keeps
  its meaning of "no LLM attempted."
- The run report dict (`:526-532`) gains `llm_error` and `rejected` counts
  alongside `llm` / `machine`, so an operator sees *why* rationales are machine.
- The `reasoning`-field fallback (3) stays but is subject to the same numeric
  validation as `content`; persisting raw CoT that fails grounding is rejected
  like any other.

### Behavioral contract

- A rationale citing only grounded numbers (within tolerance) → persisted as
  `llm` (unchanged happy path).
- A rationale citing an ungrounded number beyond the threshold → machine
  fallback, `generated_by="machine_rejected"`, original text discarded, reason
  logged. No exception propagates.
- LLM raises → `generated_by="machine_llm_error"` (today's silent `"machine"`).
- No LLM attempted (no key / not interesting) → `generated_by="machine"`.
- Validation is pure and deterministic; no network.

### Error modes

- Rationale with **no numbers** → zero unverified → always passes (qualitative
  text is allowed; the check only constrains numeric claims).
- Grounding set empty (no signals, score None) and rationale cites a number →
  that number is unverifiable → rejected (correct: the model invented a figure
  with nothing to ground it).
- Regex over-matches a year or list index → see critical review (tolerance +
  threshold absorb rare false positives; default threshold 0 is strict, but the
  fallback is a safe machine rationale, not data loss).

### Does NOT

- Re-prompt or "repair" the rationale (no second LLM call — cost/complexity).
- Validate non-numeric claims (regime names, prose) — out of scope; numbers are
  the falsifiable, high-risk surface.
- Change the prompt, the interestingness gate, or the Ollama call itself.
- Switch providers (Claude wiring is a separate, explicit decision — T2.1).

### Testable properties

1. **Grounded passes:** a rationale citing only context numbers (incl. a rounded
   form like 65 for 64.8) → `generated_by == "llm"`, text persisted.
2. **Hallucination rejected:** inject a rationale citing a number absent from the
   grounding set beyond tolerance → `generated_by == "machine_rejected"`, the
   fabricated text is NOT in the persisted `rationale_md`.
3. **No-number rationale:** qualitative-only text → passes (no false reject).
4. **LLM error path:** `_call_llm` raises → `generated_by == "machine_llm_error"`
   and the run report's `llm_error` count increments.
5. **Report accounting:** a run mixing happy / rejected / errored / not-interesting
   segments yields the correct four counts summing to `total`.
6. **Determinism:** validation is pure — same (text, context) → same verdict.

---

## Critical review (one pass, per CLAUDE.md SDD)

- **False positives are the main risk.** A regex for numbers will catch years
  ("2026"), enumerators ("1."), and HS codes the prompt legitimately shows. Two
  mitigations already in the design: (a) the grounding set includes everything
  the prompt displayed (signal values, dates' numeric parts can be added if
  needed), and (b) the *consequence of a false reject is a safe machine
  rationale, not data loss or a crash*. So strict default (threshold 0) is
  acceptable — worst case we under-use a valid LLM rationale, which is the
  conservative direction for a trust feature. We will **log every rejection with
  the offending number** so false-positive rate is observable and the threshold
  can be tuned from real data rather than guessed.
- **Should `observed_at` dates count as grounding?** The model is shown dates;
  it may cite a year. Decision: include the **integer year/month parts** of the
  shown dates in the grounding set so legitimate date citations pass. Cheap, kills
  the most common false positive.
- **Simpler alternative — just check that any cited signal *name* appears in
  context (string match), skip numbers.** Rejected: names are rarely hallucinated;
  *numbers* are the dangerous surface (a wrong value reads as authoritative). The
  numeric check is the one that earns its keep.
- **Alternative — LLM-as-judge second call to grade faithfulness.** Rejected:
  doubles cost/latency, adds a second hallucination surface, and is
  non-deterministic — antithetical to a validation gate. A pure numeric check is
  testable and free.
- **Threshold as 0 vs >0.** Start at 0 (strict) but make it a named constant so
  it's trivially tunable once we see the real false-positive rate from the logs.
  Document that it's a policy knob, not a magic number.
- **Backward-compat:** `generated_by` gains two new string values. The DB column
  is free-text (no enum/constraint — verify in `models.py` during impl; if there's
  a CHECK constraint this needs a migration). The frontend renders the string
  verbatim ("generated by {generated_by}") so new values display fine. Run-report
  dict gains keys — additive, no consumer breaks.
- **Interaction with T1.4:** none — different files (`research_daily.py` vs
  `stats.py`/`backtest.py`). Safe to implement in parallel; no shared surface.

---

## Implementation order (when approved)

1. New pure helper `_validate_numeric_claims(rationale: str, context, score_row)
   -> list[float]` (returns unverified numbers) + grounding-set builder, with the
   tolerance/threshold constants. Unit-tested in isolation.
2. Wire into `_generate_for_segment_horizon` (`:370-390`): on LLM success, run
   validation; reject → machine fallback tagged `machine_rejected`; distinguish
   `machine_llm_error` in the `except`.
3. Extend the run report counts (`:516-532`) with `llm_error` + `rejected`.
4. Verify the `ResearchSnapshot.generated_by` column has no constraint
   (`app/db/models.py`); add a migration only if one exists.
5. Tests: the 6 properties (new cases in `test_research_daily.py`).
6. Frontend: no change required (renders the tag verbatim); optionally surface
   the new counts if a research status view exists.
```
