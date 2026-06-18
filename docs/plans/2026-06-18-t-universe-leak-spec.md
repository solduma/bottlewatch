# Spec: Point-in-time universe leak in backtest baskets

**Date:** 2026-06-18
**Covers:** the basket-construction leak fenced off from T1.4 (see
`2026-06-18-t14-backtest-inference-spec.md` critical review).
**Why spec-first:** point-in-time correctness in money-sensitive backtest
logic. Per CLAUDE.md SDD.

---

## Problem (verified against the code)

`build_baskets` (`app/backtest/baskets.py`) selects and weights tickers using the
**current** universe CSV (`research/02_universe.csv`) applied retroactively across
the whole backtest window:

1. **Static fundamentals applied as-of every past date.** `_eligible_tickers`
   (`baskets.py:105-119`) filters on `mcap_usd >= $2B` and `exposure_pct >= 50%`
   from today's CSV values. A company that was sub-$2B in 2024 but is $5B today
   passes the 2024 eligibility check using its 2025 size — look-ahead.
   `score_contribution = exposure_pct * score` (`:356`) and the eligibility sort
   (`:340`) use the same present-day values.
2. **Survivorship.** The universe CSV lists only tickers that exist *today*.
   Names delisted/acquired/renamed mid-window are simply absent, so baskets are
   built from known survivors.
3. **Membership leak.** A ticker is "in" a segment for the entire window based on
   today's mapping, regardless of when it actually became a member.
4. **(Efficiency, not a leak) CSV re-read per eval date.** `build_baskets` calls
   `_load_universe(universe_path)` (`:480`) on *every* eval date inside the job's
   date loop (`backtest.py:261,279`) — O(eval_dates × universe) redundant parse.

### Hard constraint discovered

There is **no historical universe data** in the project: `mcap_usd` /
`exposure_pct` exist only as static CSV columns; there is no shares-outstanding
series, no point-in-time membership table, and no delisting record (confirmed:
nothing time-varying in `models.py` / `prices.py`). Therefore items 1–3 **cannot
be fully corrected** — there is no as-of value to substitute. The honest options
are: (a) a partial as-of gate using the one time-varying signal we *do* have
(prices → listing existence), and (b) explicit disclosure of the residual,
rather than presenting basket returns as point-in-time clean.

---

## Design

Scope = **what's achievable without inventing data** + **stop pretending the rest
is clean**. Two real fixes, one efficiency fix, one disclosure.

### A. As-of listing gate (the one true point-in-time fix available)

A ticker can only be in a basket at `t` if it had a **price bar on or before `t`**
(it was actually trading then). Today a not-yet-listed ticker is still added to
`entries`/`weights` and only silently drops out of the *return* calc via coverage.

- In `_build_basket` / `_build_watchlist`, after selecting `chosen` rows, drop any
  ticker with no price bar at-or-before `eval_date` (reuse
  `_find_close_on_or_before(prices.get(ticker, []), eval_date) is None`).
- This removes the most concrete survivorship/membership leak we *can* detect:
  a basket no longer "holds" a ticker that wasn't trading yet, and weights
  renormalize over genuinely-held names.
- Tickers with no price data **at all** are likewise excluded (they contribute
  nothing but noise to coverage today).

### B. Make the static-fundamental leak explicit, not silent

- Add a module docstring + a `Basket.fundamentals_asof: str` field (or reuse a
  report-level note) recording that `mcap_usd`/`exposure_pct` are **static
  present-day values**, not as-of. Surface a single per-run disclosure in the
  `BacktestReport` (new field `universe_is_point_in_time: bool = False` +
  `universe_caveat: str`) so the JSON/UI states the limitation in-band.
- Do **not** fabricate historical mcap/exposure. Document the gap as a known
  follow-up (needs a point-in-time fundamentals source).

### C. Load the universe once (efficiency)

- Change `build_baskets` to accept `universe_rows: list[UniverseRow]` instead of
  re-reading `universe_path` per call; load once in the job (`backtest.py`) before
  the eval-date loop and pass the parsed rows in. Keep a thin `universe_path`
  convenience overload only if needed by other callers (check `test_*` + API).

### Behavioral contract

- A ticker not trading at `t` (no bar ≤ `t`) → excluded from the basket at `t`
  (not merely zero-return). Baskets shrink to genuinely-listed names; `min_tickers`
  underflow stays a soft warning (unchanged policy).
- Eligibility/sort/score_contribution still use static mcap/exposure (no data to
  do otherwise) — but the report now **declares** this rather than implying
  cleanliness.
- `build_baskets(universe_rows=...)` is the new signature; the job loads once.
- No change to score gating (already point-in-time via `_b_at`), forward-return
  math, or the T1.4 IC path.

### Error modes

- Empty prices for every selected ticker → empty basket, coverage 0.0 (as today).
- `universe_rows` empty → empty baskets (as today with empty CSV).

### Does NOT

- Invent historical mcap/exposure/membership (no source exists).
- Change transaction-cost model, volatility annualization, or rebalancing (those
  are separate basket-realism items, not point-in-time leaks).
- Touch scoring, ingestion, or the IC inference.

### Testable properties

1. **As-of gate:** a ticker whose first price bar is *after* `t` is **not** in the
   basket built at `t` (today it would be, with the static row).
2. **Listed ticker retained:** a ticker trading at `t` is included as before.
3. **No-price ticker excluded:** a selected-eligible ticker with no price series
   is absent from the basket entries.
4. **Load-once:** `build_baskets` no longer reads the CSV; given `universe_rows`
   it builds identical baskets to the old path for a fully-listed universe
   (regression: same tickers/weights when all bars precede `t`).
5. **Disclosure:** `BacktestReport.universe_is_point_in_time is False` and the
   caveat string is non-empty.
6. **Efficiency (light):** the job parses the universe CSV once regardless of
   eval-date count (assert `_load_universe`/`build_baskets` no longer takes a path,
   or count parses via a spy).

---

## Critical review (one pass, per CLAUDE.md SDD)

- **Biggest risk: am I overstating the fix?** Yes if I imply the leak is "fixed."
  It is **not** — static mcap/exposure remain a real look-ahead we cannot remove
  without historical fundamentals. Mitigation is the whole point of part B: the
  report must say so. The achievable win is the listing/survivorship gate (A),
  which is genuine and testable. Framing in the commit/PR must be "reduce +
  disclose," not "eliminate."
- **Does the as-of gate change historical results a lot?** Possibly — baskets that
  silently included not-yet-listed names (counted only via coverage) will now
  exclude them up front, shifting weights. That's the correct direction (we stop
  holding things that didn't trade). The existing coverage field already hinted at
  this; we're making it a membership decision instead of a return-time dropout.
- **Simpler alternative — only do C (load-once) + B (disclosure), skip A.**
  Rejected: A is the one concrete point-in-time correctness gain actually
  available; skipping it would leave the headline leak (holding unlisted names)
  in place. C alone is just perf.
- **Alternative — drop basket backtesting entirely until a PIT universe exists.**
  Rejected: too blunt; the IC path is still useful and the listing gate materially
  improves basket realism. Disclosure handles the residual honestly.
- **Contract/back-compat:** changing `build_baskets` from `universe_path` to
  `universe_rows` is a breaking signature change — must update the job and ALL
  callers/tests (the basket tests build via a tmp CSV path today). Check
  `test_backtest_baskets.py`, `test_backtest.py`, and any API caller; provide the
  parsed rows in tests via `_load_universe(tmp_csv)`. Report-field additions are
  additive (TS interface gains optional fields, render the caveat).
- **Interaction with T1.4:** the IC path is independent; only the basket snapshots
  change. The new report fields sit alongside T1.4's additions — no conflict.
- **Is the listing gate itself look-ahead-free?** Yes: it uses only prices dated
  `<= t`, which are point-in-time by construction (unlike fundamentals).

---

## Implementation order (when approved)

1. `baskets.py`: add the as-of listing gate in `_build_basket` + `_build_watchlist`;
   change `build_baskets` to take `universe_rows`; module docstring on the static-
   fundamental caveat.
2. `backtest.py`: load universe once before the loop; pass rows; populate the new
   report disclosure fields.
3. `basket_report.py`: add `universe_is_point_in_time: bool = False` +
   `universe_caveat: str` to `BacktestReport` (additive).
4. Tests: the 6 properties (extend `test_backtest_baskets.py`; adjust callers to
   the new signature; a job-level assert for load-once + disclosure).
5. Frontend: TS `BacktestReport` gains the two fields; render the caveat as a
   visible banner on the backtest page.
6. PR framing: "reduce + disclose the universe leak," explicitly NOT "eliminate";
   note the historical-fundamentals gap as the remaining follow-up.
```
