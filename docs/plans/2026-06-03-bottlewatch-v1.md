# Bottlewatch — Implementation Plan

A two-tier dashboard for a solo investor monitoring the AI supply chain,
surfacing binding bottlenecks and the public companies exposed to them.
Investment-first. Research-then-build. v1 deliverable: research report +
end-to-end value chain map + working dashboard with daily refresh on key metrics.

---

## 1. Project layout

```
bottlewatch/
├── pyproject.toml              # uv-managed; Python 3.13
├── README.md
├── Makefile                    # research, ingest, api, web
├── research/                   # Phase 1 deliverables (markdown + diagrams)
│   ├── 00_value_chain.md
│   ├── 00_value_chain.mmd      # Mermaid source, canonical artifact
│   ├── 00_value_chain.json     # parsed DAG for React Flow consumer
│   ├── 01_segments/            # one .md per segment
│   ├── 02_universe.csv         # human-edited ticker → segment → exposure%
│   ├── 03_data_sources.md      # free vs gated, workarounds
│   ├── 04_scoring_methodology.md
│   └── 05_ontology/            # OWL/RDF ontology
│       ├── bottlewatch.owl     # TBox (Protégé-authored)
│       └── instances.ttl       # ABox (generated from CSV + Mermaid)
├── data/
│   ├── raw/                    # immutable dumps (gitignored)
│   ├── processed/              # normalized parquet/csv (gitignored)
│   └── cache/                  # API responses w/ TTL
├── src/
│   └── bottlewatch/            # hatchling package (editable install)
│       ├── app/                # FastAPI app (M1+)
│       │   ├── main.py
│       │   ├── routers/{segments,signals,tickers,screener,scores,thesis}.py
│       │   ├── models/         # pydantic + sqlalchemy
│       │   ├── services/       # scoring, normalization, ontology wrapper
│       │   └── ingest/         # per-source adapters
│       ├── jobs/               # one-shot CLI jobs (build, validate, refresh)
│       │   ├── build_ontology.py
│       │   ├── validate_ontology.py
│       │   ├── refresh_daily.py
│       │   └── recompute_scores.py
│       └── tests/              # pytest, co-located
├── frontend/                   # Next.js 15 (App Router) + TypeScript
│   ├── app/{overview,segment/[slug],tickers,thesis,map}/page.tsx
│   ├── components/{Chart,ScoreCard,SegmentTable,HorizonToggle,TickerDrawer,Sparkline}.tsx
│   └── lib/api.ts
├── notebooks/                  # exploratory analysis, throwaway
└── docs/
    ├── plans/                  # design / implementation plans
    └── adr/                    # architecture decision records
```

Tooling: `uv` for Python, `pnpm` for the frontend, `launchd` plist for the
daily refresh on the macOS host.

---

## 2. Research phase (Phase 1) — M0

**Sequencing:** breadth-first — every segment gets the same depth before any
is picked as the conviction call. Avoids confirmation bias. Top 1-2 segments
emerge from scoring, not from a prior.

**Legwork:** I run the full research (web, filings, transcripts, sell-side
notes, trade press) and synthesize. You review drafts.

**Source priority for M0 (in order):**
1. Filings & IR (10-K/10-Q, 8-K, earnings transcripts, IR decks) — primary
   source for capacity, capex, customer concentration language.
2. Sell-side & expert calls (Citi/MS/GS AI supply-chain notes, expert
   networks, sell-side conferences) — high signal, often paywalled; use
   summaries you have access to; otherwise rely on published notes.
3. Government & regulatory (FERC interconnection queue, EIA-860,
   EPA eGRID, BLS, Census, EU/KR/TW equivalents) — highest-quality,
   mostly free.
4. Trade press & industry associations (EE Times, SemiAnalysis, Reuters,
   SEMI, AFCOM, conference proceedings like Hot Chips).
5. News & blogs — used for color and timeliness, not load-bearing claims.

Deliverable sequence: map → segments → universe → sources → scoring.

### 2.1 End-to-end value chain map (`research/00_value_chain.mmd`)

**Shape:** a directed acyclic graph (DAG) with two parallel upstream tracks
that converge at the data center, then flow downstream to inference. Every
node carries an explicit **"suppliers of this segment"** sub-list — the
supplier-of-supplier step the user asked for. Lineage is preserved by
treating the graph as nested, not flattened: clicking a node expands its
supplier subgraph, and the upstream path is traversable indefinitely.

**Bird's-eye view (the main spine):**

```
                                    ┌─ power generation OEMs (GEV, Siemens Energy, MHI, BWXT)
fuel & power inputs ── T&D utilities ─┤
(XOM, CVX, CCJ, FCX)  (NEE, SO, DUK,  ├─ transformers & switchgear (GEV, HUBB, Eaton, Hitachi)
                       AEP, Iberdrola)│
                                    └─ data center shell (EQIX, DLR, hyperscalers)
                                                    ▲
raw inputs ── semiconductor materials ── front-end equip ── advanced fabs ──┐
(silica, gases)(Shin-Etsu, JSR, Linde)  (ASML, AMAT, LRCX) (TSMC, Samsung)   │
                  │                                                       │
                  └─ advanced pkg / HBM ── HBM ── networking ── GPU/ASIC ──┤
                     (TSMC, ASE, Amkor)    (hynix)  (AVGO, Arista) (NVDA)  │
                                                                          ▼
                                              systems OEMs/ODMs (SMCI, Dell, Quanta) ── rack-scale integration (NVDA, Vertiv, Schneider)
                                                                                              │
                                                                                              ▼
                                                                              cooling & water (WTS, Trane, Ecolab)
                                                                                              │
                                                                                              ▼
                                                                              inference at scale (hyperscalers + neoclouds)
```

**Per-node supplier annotations** (the extra step; one tier back, kept as
edge labels in the Mermaid source so the bird's-eye view stays readable):

| Node | Direct suppliers (one tier back) |
|---|---|
| raw inputs | oil & gas majors, mining (FCX, SCCO), municipal water utilities, ISMR/SMR fuel cycle |
| semiconductor materials | raw inputs; specialty chemicals (Dow, DuPont, Mitsui) |
| front-end equipment | semiconductor materials; optical components (Carl Zeiss); precision robotics |
| advanced node fabs | front-end equipment; semiconductor materials; municipal water utilities; power utilities |
| advanced packaging | advanced node fabs; HBM as a sub-input; substrate makers (Ibiden, Shinko, Unimicron) |
| HBM memory | advanced node fabs (foundry); advanced packaging (stacking); semiconductor materials |
| networking / interconnect | semiconductor materials; optical components (Lumentum, Coherent); substrate makers |
| GPU/ASIC silicon | advanced node fabs; HBM; advanced packaging; networking; on-die power delivery |
| systems OEMs/ODMs | GPU/ASIC silicon; networking; power supplies (Delta, Lite-On); chassis/metal |
| rack-scale integration | systems; CDUs/pumps (CoolIT, Vertiv); busbars; power shelves |
| data center shell | rack-scale integration; power utilities; water utilities; networking carriers; REITs |
| cooling & water | chillers (Trane, Carrier, JCI); pumps (Flowserve, Xylem); water utilities; chemicals (Ecolab) |
| power generation OEMs | rare earths (MP, USA Rare Earth); nuclear fuel; solar/wind (First Solar, Jinko); gas turbines (GEV, Siemens Energy) |
| transformers & switchgear | electrical steel (Cleveland-Cliffs); copper; insulation; power generation OEMs as customers |
| T&D utilities | transformers; power generation; regulators (FERC, state PUCs, ISO/RTOs) |
| fuel & power inputs | oil & gas (XOM, CVX, OXY); uranium (CCJ, KAP); mining (FCX, SCCO); renewables developers |
| inference at scale | everything upstream; no further supplier chain |

**Frontend rendering (`/map` page):**

- Mermaid for the static fallback (good enough for sharing a link).
- Custom React renderer for the live dashboard view, built on **React Flow**
  (or **D3** if we need the DAG layout to scale past ~100 nodes).
- **Node coloring by bottleneck score** (using the §7 scorecard, with a
  horizon toggle at the top — same `near` / `med` / `long` switch as the
  scoreboard):
  - 0-20: green (ample capacity)
  - 20-40: yellow-green
  - 40-60: yellow
  - 60-80: orange
  - 80-100: red (binding bottleneck)
- **Click behavior:** clicking a node opens a side panel (or modal) showing:
  1. The node's current bottleneck score and the 5 sub-scores
  2. A ranked list of public companies in that node (from
     `02_universe.csv`) with their exposure %, market cap, and last
     computed score contribution
  3. A "drill upstream" button that re-centers the canvas on the node and
     fades non-supplier edges, so the user can navigate the supply
     lineage indefinitely without losing context
- **Edge thickness** = relative flow value (spend, kWh, or units — TBD
  during M1; v1 may just use a constant thickness and document it as
  "qualitative flow").
- **Layout:** dagre / elkjs for the auto-arranged DAG; user can pan, zoom,
  and click-to-focus. Breadcrumb at the top shows the current focus path
  (e.g. `inference → data center → transformers → electrical steel`).

**Why a navigable graph, not a static Mermaid in the dashboard:** the user
explicitly wants to navigate upstream from any node. Mermaid SVG doesn't
support click-to-recenter. React Flow + a small state store (Zustand) for
focus path + horizon + score range is the right tool.

**Lineage preservation:** the Mermaid source remains the canonical artifact
in `research/00_value_chain.mmd` — same supplier annotations, just encoded
as edge labels rather than a hand-drawn two-track diagram. The dashboard
renderer reads the same source (parsed via a small custom parser, not the
Mermaid JS lib, since we need score overlays React Flow doesn't have).

Saved as Mermaid source for the static version; React Flow consumes the
same data via a normalized JSON export (`research/00_value_chain.json`)
that the backend API serves at `GET /v1/map`.

### 2.2 Per-segment deep dive template (`research/01_segments/<slug>.md`)

Fixed template per segment:
1. Definition & boundary (NAICS codes)
2. Demand drivers (training compute, inference, sovereign AI) with units
3. Supply side: capacity, lead times, utilization
4. Chokepoints (geo concentration, single-vendor, regulatory)
5. Public players: tickers, %-exposure, market cap
6. Lead indicators (3-7 metrics tracked daily/weekly)
7. Open questions / data gaps

### 2.3 Investable universe (`research/02_universe.csv`)

Columns: `ticker, exchange, name, segment, subsegment, exposure_pct,
market_cap_bucket, mcap_usd, currency_hedge, notes`.

Composition (per user):
- **Pure-plays + adjacent** — include diversified industrials (GE Vernova,
  Schneider, Honeywell) as adjacent exposure.
- **Local listings + manual hedge** — keep Tokyo/Seoul/Taipei/Frankfurt
  listings at home; FX hedged manually in the broker account. `currency_hedge`
  column captures the intended hedge instrument.
- **Large + mid-cap** — drop sub-$2B names for v1; revisit later.
- Target: ~100-150 names.

### 2.4 Data gap & source assessment (`research/03_data_sources.md`)

Per source: free?, API key?, rate limits, freshness, historical depth,
known gotchas, fallback. See §6 for the v1 source list.

### 2.5 Bottleneck scoring methodology (`research/04_scoring_methodology.md`)

Formula, input signals, worked example for the top pick, backtest
methodology. Defendable conviction, not vibes. See §7.

**M0 exit criteria:** map rendered, 8-12 segment briefs, universe CSV
populated, scoring v1 documented, data sources assessed, conviction picks named.

---

## 3. Data pipeline

Stack: `httpx` + `tenacity` for HTTP, `polars` for transforms, `sqlalchemy`
+ `sqlite` (v1) → `postgres` later, `pydantic-settings` for config.

Common schema:

```
signals(segment, subsegment, signal_name, value_num, value_text, unit,
        geography, source, source_id, observed_at, ingested_at, released_at,
        tickers JSON)
```

`released_at` is nullable and is the point-in-time gate for historical
recomputes; when absent the recompute job falls back to `ingested_at`. The
production daily path ignores the column and loads the latest signals.

### 3.1 Adapters (`src/bottlewatch/app/ingest/`)

One module per source, each exposing
`fetch(period_start, period_end) -> list[RawSignal]`:

- `sec_edgar.py` — EDGAR full-text for 10-K/10-Q capacity language, capex,
  customer concentration; 8-Ks.
- `sec_insider.py` — Form 4 clustering on universe tickers (smart-money signal).
- `fred.py` — `fredapi` for IP, PPI, ISM, interest rates, capacity utilization.
- `eia.py` — `eiapy` / REST for electricity load, generation mix, capacity
  additions; EIA-860 + 860M for generator inventory.
- `eia_electric.py` — short-term energy outlook, retail sales by sector.
- `usitc.py` / `comtrade.py` — HBM (HS 8542/8541), lithography (HS 8486),
  transformers (HS 8504). UN Comtrade for global mirror.
- `epa_egrid.py` — eGRID emissions/water intensity by subregion (IDC siting).

Each adapter has a unit test with a recorded VCR-style fixture so CI runs
offline.

### 3.2 Storage

SQLite at `data/processed/bottlewatch.db` for v1. Move to Postgres when
write QPS > 50 or when concurrent refresh + API is needed. `alembic`
migrations from day 1 so the Postgres cutover is just `DATABASE_URL=...`
and `alembic upgrade head`.

### 3.3 Refresh orchestration

`src/bottlewatch/jobs/refresh_daily.py` invoked by a `launchd` plist on the macOS
host. Each adapter declares its own cadence (`@daily`/`@weekly`/`@monthly`);
orchestrator reads a `last_ingested_at` watermark and skips fresh sources.
Logs to `data/cache/refresh.log`. Phase 2 candidate: GitHub Actions cron
for resilience when the laptop is asleep.

---

## 4. Backend API (FastAPI)

```
GET  /v1/segments                          # list + metadata
GET  /v1/segments/{slug}                   # segment detail incl. score + momentum history
GET  /v1/segments/{slug}/signals           # time series, ?horizon=near|med|long
GET  /v1/scores                            # current scores (B and B') per segment
GET  /v1/scores/regime                     # 2x2 quadrant payload: B, B', regime label, ETA per (segment, horizon)
GET  /v1/scores/history                    # per-segment B and B' over time
GET  /v1/tickers                           # universe, filters: segment, mcap, geo
GET  /v1/tickers/{ticker}                  # ticker → segment exposures, signals
GET  /v1/screener?side=long|short&horizon= # conviction picks
                                          # long: excludes RESOLVING segments (§7.4 hard guard)
                                          # short: returns RESOLVING segments ranked by B × |B'|
GET  /v1/eta                               # resolution ETA per segment (?horizon=)
GET  /v1/map                               # value chain DAG: nodes (with regime) + edges
GET  /v1/map/{slug}                        # node detail: companies + sub-scores + regime + ETA + upstream path
POST /v1/thesis                            # user-authored notes (sqlite)
```

Cached reads via `functools.lru_cache` + 5-min TTL on most endpoints;
signal series cached per `(segment, signal, from, to)`. Auth: none for v1
(localhost only). Add API-key middleware before any external exposure.
Pydantic models throughout. `uvicorn --reload` in dev.

---

## 5. Frontend (Next.js 15 App Router + TypeScript)

Charting: **Recharts** for time-series / bar / heatmap on segment and
ticker pages. For the navigable value chain see `/map` below.

Pages:
- `/` — **Regime quadrant (the primary view)**: a 2x2 of B(s,h) × B'(s,h)
  per §7.2. Each cell of the quadrant shows segment badges colored by
  regime (EMERGING/PEAKING/PEAKED/RESOLVING/STABLE). Click a badge → segment
  detail. The top of the page shows three derived lists: **proactive longs**
  (EMERGING), **shorts / avoid-long** (RESOLVING), **watchlist** (rising
  from low). Horizon toggle (near/med/long) at the top — the quadrant
  reshapes per horizon.
- `/segment/[slug]` — **Drilldown**: side-by-side B and B' traces
  (sparkline + 6mo delta), the 5 sub-scores, the resolution ETA panel
  (announced capacity, demand cooling signals, permit buffer), the
  conviction basket or short candidate the regime implies, top tickers
  table, embedded segment brief markdown.
- `/tickers` — **Screener**: filterable table; columns ticker, segment,
  exposure%, mcap, last B, last B', regime, last insider cluster, "add to
  basket" (session-local). Filter by side (`long` / `short`) — the long
  filter applies the §7.4 hard guard automatically.
- `/thesis` — **Notes**: TipTap markdown editor per segment/ticker,
  persisted via `/v1/thesis`. The override-audit-trail for the hard guard
  lives here: a user who wants to argue against a RESOLVING regime writes
  a thesis note linked to the basket entry.
- `/map` — **Value chain graph**: navigable upstream DAG. **React Flow**
  (with `dagre` / `elkjs` for auto-layout) consuming the `GET /v1/map`
  response. Features:
  - Nodes colored by regime (not just current score) — EMERGING cells
    glow green, RESOLVING cells fade red, etc. Horizon-aware.
  - Click a node → side panel with sub-scores, B/B' traces, ranked
    company list, and a one-line regime + ETA summary
  - "Drill upstream" button → recenters on the node, fades non-supplier
    edges, updates a breadcrumb
  - Pan/zoom/focus freely without losing the upstream lineage
  - v1 ships a static Mermaid SVG as a shareable fallback
  - v2 candidate: replace with Visx/D3 for Sankey-style flow magnitudes

State: TanStack React Query for server state, Zustand for UI state (focus
path, horizon, regime filter, selected node).

---

## 6. v1 data sources (7 picks, ranked by signal/noise)

1. **SEC EDGAR full-text** (`efts.sec.gov`) — 10-K/10-Q capacity language,
   capex, customer concentration. *Free, no key, generous limit.*
2. **EIA Open Data** (`api.eia.gov/v2`) — electricity load, generation mix,
   regional capacity. **Headline source for the power-bottleneck thesis.**
   Free key, email signup.
3. **EIA-860 / 860M** — generator inventory, planned additions, retirements.
   Direct download, refresh monthly.
4. **FRED** (`api.stlouisfed.org`) — IP, capacity utilization, PPI
   semiconductors, ISM PMI, rates, credit spreads. Free key.
5. **UN Comtrade** (`comtradeapi.un.org`) — HBM, lithography, transformer
   trade flows by HS code. Free key, daily limits; USITC DataWeb for US-side.
6. **EPA eGRID / EJSCREEN** — subregional emissions & water-stress overlays
   for IDC siting. Free downloads, no API.
7. **Form 4 insider filings** (SEC) — cluster buys on universe tickers.
   Free, high-signal early indicator.

Defer to v2: Bloomberg/Refinitiv, sell-side AI supply-chain notes, S&P
Capital IQ capex trackers, satellite imagery of IDC construction.

---

## 7. Conviction scoring (v1 formula)

The plan as originally written scored a static snapshot. Per the user, that's
not enough — the user wants to **predict** the bottleneck, not just locate
it. Three cases matter:

1. **EMERGING** (low score, rising fast) — proactive long before consensus
2. **PEAKING / PEAKED** (high score, plateauing) — momentum long or trim
3. **RESOLVING** (high score, falling) — short or skip; do NOT long

The failure mode the user explicitly flagged: long a segment that *looks*
bottlenecked today but is about to be relieved by announced capacity. The
scoring engine and the basket builder both have to make this failure mode
structurally hard to commit.

### 7.1 Two-axis scoring: level + momentum

Two scores per segment, per horizon:

- `B(s, h)` — current level, 0-100, tighter = higher. Same formula as
  originally specified.
- `B'(s, h)` — **momentum**, the 6-month backward-looking delta of `B`,
  in the range [-100, +100], positive = tightening.

```
B(s, h)   = 100 * Σ_i w_i(h) * normalize(s_i)                   # level, 0-100
B'(s, h)  = median(B(s, h, t') for t' in [t-6mo-15d, t-6mo+15d])  # momentum, -100..+100
```

Backward-looking delta was chosen over forward pressure / state-space
models for v1 because it's transparent, easy to backtest, and the failure
mode (lagging a real inflection) is a known cost we can compensate for
with leading indicators (see §7.3). v2 can add a forward term.

**M2 momentum implementation note:** the formula above differs from
the original v1 spec (`B(s,h,t) - B(s,h,t-6mo)` is a point-to-point
delta). The median over a 30-day window around t-6mo was adopted in
M2 to dampen the noise of single-night recomputes — a single
`ingest_runs` blip on t-6mo would otherwise cause a 100-point
momentum flip. The plan-to-code change is recorded here so a
reader of the M2 code (`app/score/formula.py:_momentum`) does not
chase a regression.

### 7.2 The 2x2 regime quadrant

Cross the two axes into a quadrant with a regime label and a **suggested
trade action**:

```
                       B'(s, h)  ──────────────────────────────►
                                 tight-         plateau-      loosening
                                 ening                         fast
                  ┌──────────────┬──────────────┬──────────────┐
   B(s, h)        │  EMERGING    │  PEAKING     │  RESOLVING   │
   high           │              │              │              │
                  │ trim longs   │ hold / trim  │ SHORT or     │
                  │ — too late   │  (no new)    │  skip longs  │
                  ├──────────────┼──────────────┼──────────────┤
                  │  EMERGING    │  STABLE      │  RESOLVING   │
   B(s, h)        │  ★ PROACTIVE │              │              │
   low            │    LONG ★    │  wait        │  not yet a   │
                  │              │              │  long        │
                  └──────────────┴──────────────┴──────────────┘
```

The dashboard's `/` (scoreboard) page is **this quadrant** — not a ranked
list. Each cell is a segment badge colored by quadrant; clicking opens the
segment detail with `B` and `B'` traces and the conviction basket (or
short candidate) the regime implies.

**Regime labels are computed, not opinionated.** The mapping is calibrated
in `research/06_regime_thresholds.json`; that file is the **canonical
source of truth** for the B / B' thresholds and the `data_completeness`
gate. The `regime.classify(...)` function in `app/score/regime.py` reads
the JSON at import time; the v1 numbers below are the historical
placeholders, kept here for context.

| Cell        | M2 calibration (from `06_regime_thresholds.json`) | Original v1 placeholder |
| ----------- | ------------------------------------------------- | ----------------------- |
| B ≥ 70      | B' ≥ +20 → PEAKING                                | B ≥ 60, B' > +5         |
| B ≥ 70      | 0 ≤ B' < +20 → PEAKED                             | B ≥ 60, B' ∈ [-5, +5]   |
| B ≥ 70      | B' < 0 → RESOLVING (fast_resolve if B' < -50)     | B ≥ 60, B' < -5          |
| B < 70      | B' ≥ +30 → EMERGING (★ proactive long)            | B < 60, B' > +5          |
| 30 ≤ B < 70 | -15 ≤ B' < +30 → STABLE                           | B < 60, B' ∈ [-5, +5]    |
| B < 30      | B' ≤ -15 → RESOLVING-from-low                     | B < 60, B' < -5          |

The M2 calibration raised the B threshold from 60 to 70 and widened the
B' bands (±5 → ±20/0/±30/-15) so the scoreboard surfaces fewer
PEAKING / EMERGING labels on segments that have merely trended up — the
60/±5 placeholders produced too many regime flips for a one-trimester
view. On recalibration, bump `version` in the JSON and update the table
above in the same commit.

`regime.confidence` is `low | medium | high` based on the age of
`first_computed_at` for the (segment, horizon) row — fewer than 90
days of recompute history is `low`, 90-180 days is `medium`, beyond is
`high`. The 7th label, `NO_DATA`, is the synthetic "not enough
sub-scores to score meaningfully" gate at `data_completeness < 0.4`.

### 7.3 Resolution ETA — when does the bottleneck ease?

`B'(s, h)` is backward-looking. It tells you the bottleneck is loosening,
but not whether it will continue to loosen or hit a floor. A separate
**resolution ETA** estimates when the segment's `B` will drop below 50,
based on four input streams (per user):

1. **Announced capacity additions** — EIA-860 monthly generators (power
   segments), 10-K capex tables with commissioning dates (semis,
   packaging), supplier guidance on ramp schedules (HBM, transformers).
   Each addition has a `commissioning_date` and a `capacity_delta`; we
   subtract from the existing tightness.
2. **Leading indicators** — book-to-bill ratio, lead-time quotes,
   customer pre-pays / deposits. The classic "this is going to inflect
   soon" signal: book-to-bill has been <1 for 2 quarters while capex
   is still ramping. Easiest to source for semis (SEMI publishes B/B),
   harder but doable for power (utility IR decks).
3. **Demand cooling signals** — hyperscaler capex guidance (deceleration
   = relief), IDC pre-lease rates (cooling = demand easing), neocloud
   funding rounds (slowdown = demand easing), sovereign AI commitments
   (postponements = demand easing).
4. **Regulatory / permitting timeline** — FERC interconnection queue
   position, environmental permits, export control timelines. Determines
   whether announced capacity actually delivers on schedule.

These four streams feed a small model:

```
ETA(s) = earliest (commissioning_date + permit_buffer) where
         cumulative_capacity_delta >= demand_growth_until_then
         AND demand_cooling_signal not yet accelerating
```

The result is a `(date, confidence)` tuple per segment. The dashboard
displays it on the segment detail page as a single line: "Relief
expected: 2027 Q2 (medium confidence), via TSMC AP7 ramp."

**Implementation note for v1:** the four streams are partially populated.
- Announced capacity: easy (EIA-860, 10-K tables, IR decks).
- Leading indicators: hard for power, doable for semis (SEMI B/B).
- Demand cooling: doable (hyperscaler capex is the easiest to track).
- Permitting: hard to systematize; v1 uses a hand-curated buffer per
  segment (e.g. "AP7 +0 months", "SMR +24 months").

This is the part of the model most likely to be wrong on day one. v1
ships a *directional* ETA ("relieves in <12mo" / "12-24mo" / ">24mo")
rather than a precise date. Precision comes with M4 backtest.

### 7.4 The hard guard in the basket builder

The user's clearest directive: "I don't want to wrong-position just
because it is currently bottlenecking (resolution in near future can
damage the long position)."

The conviction basket builder **refuses** to add a ticker whose segment
is in `RESOLVING` regime to the **long** basket, with no override. The
mechanics:

- `/v1/screener?side=long` filters out any (segment, ticker) pair where
  the segment's regime ∈ {RESOLVING} for the chosen horizon.
- The same endpoint, with `side=short`, returns segments in RESOLVING
  with the highest `B × |B'|` (tighter and loosening fastest).
- The 2x2 quadrant UI makes the regime visible at basket-build time so
  the user can see the guard fire, not just be silently filtered.

This is a **hard** guard, not a soft warning. The user's stance: "I
trust the model on this rule, override later if I have a thesis that
contradicts it." A thesis that contradicts a RESOLVING regime should
be written in `/thesis` and linked to the basket — that becomes the
audit trail, not a button to bypass the guard.

### 7.5 The full conviction pipeline (v1)

Putting §7.1-7.4 together, the conviction pipeline is:

```
for each segment s, for each horizon h:
    1. compute B(s, h)             # level (§7.1)
    2. compute B'(s, h)            # momentum (§7.1)
    3. assign regime(s, h)         # 6-cell quadrant (§7.2)
    4. compute ETA(s)              # resolution estimate (§7.3)
    5. for each ticker t in s:
         exposure = t.exposure_pct × B(s, h)
    6. build baskets:
         long basket h  = top 1-2 segments in {EMERGING, PEAKING} ∪ STABLE-for-long
                          ∩ exposure ≥ min_threshold
                          ∩ (RESOLVING segments excluded — hard guard)
         short basket h = top segments in {RESOLVING} ∩ (B × |B'|) ≥ min_threshold
         watchlist h    = segments in EMERGING-from-low (too early to trade)
```

The 2x2 quadrant is the primary view; baskets are derived from it.

### 7.6 Worked example (M0.5 agent should mirror this structure)

Hypothetical: 2026-06, "advanced packaging" segment.
- `B(advanced_packaging, near) = 78` (high; CoWoS capacity is the binding constraint)
- `B(advanced_packaging, near, t-6mo) = 91` (was higher six months ago)
- `B'(advanced_packaging, near) = -13` (clearly loosening)
- Regime: **RESOLVING** (high and falling)
- ETA: **2027 Q1** (TSMC AP7 ramp + Amkor Arizona; medium confidence)

Action: advanced packaging is **not** a long candidate. A naive read of
"high score" would have built a long basket around it; the guard prevents
that. The short candidate screen surfaces it as a top short if HBM or
GPU-pricing pressure confirms.

Compare with hypothetical "transformers": `B = 84, B' = +6`, regime
**PEAKING**, ETA **> 24mo** (permitting + SMR delays). That's a hold or
trim, not a new long. The naive scoreboard would have ranked it the
same as a still-tightening segment; the regime model disambiguates.

### 7.7 Why this matters for the investor thesis

The whole point of the dashboard is to be **earlier and more
directional** than the consensus. A static scoreboard would have you
buying what's already priced in; the regime model says "the easy money
was the EMERGING call six months ago — by the time B hits 80 it's
probably too late unless ETA is far out."

Concrete long-short duality this enables:
- Long advanced packaging 6 months ago: yes, when B was 50 and B' was
  +15 (EMERGING). Now (B=78, B'=-13) is short or skip.
- Long transformers now: not yet; B is high but B' is still positive
  (PEAKING) and ETA is far. Watch for B' to turn negative, then short.
- Long GE Vernova: depends on which role you're modeling. As
  PowerEquipmentOEM, their score mirrors the broader power segment
  which is PEAKING with medium-horizon ETA — relevant for the medium
  basket.

### 7.8 Sub-score definitions (unchanged from v1)

For completeness, the original sub-scores from the v1 spec:

- `lead_time_growth` — YoY % change in quoted lead times (packaging,
  transformers, gas turbines).
- `capacity_tightness` — orders-to-capacity ratio or utilization vs LR mean.
- `geo_concentration` — Herfindahl of supplier geography; 0 = diversified,
  1 = single-source.
- `regulatory_friction` — export controls, permitting backlog, FERC queue
  (binary flags scored by expert rubric, documented in methodology).
- `demand_signal` — hyperscaler capex guidance, IDC pre-lease rates,
  sovereign AI commitments (z-scored).

Horizon weights `w_i(h)` (unchanged):

- **near (0-12mo)**: capacity_tightness 0.35, lead_time_growth 0.30,
  demand_signal 0.20, geo 0.10, regulatory 0.05.
- **medium (1-3yr)**: capacity_tightness 0.20, lead_time_growth 0.20,
  demand_signal 0.25, geo 0.20, regulatory 0.15.
- **long (3-10yr)**: capacity_tightness 0.10, lead_time_growth 0.10,
  demand_signal 0.20, geo 0.30, regulatory 0.30.

**Conviction baskets** (per user): three baskets — near, medium, long.
The basket builder applies the §7.4 hard guard. Methodology file
documents the worked example, source of each input, and any historical
backtest.

---

## 8. Build order & milestones

**M0 — Research (3-4 weeks)**
- Deliver: value chain map, 8-12 segment briefs, universe CSV, sources
  assessment, scoring v1, named conviction picks.
- Exit: 30-min read-through shareable with a peer.

**M1 — Pipeline skeleton (1-2 weeks)**
- Repo layout per §1, SQLite schema, one adapter end-to-end (start with
  EIA), `refresh_daily.py` orchestrator, basic tests.
- Exit: `make ingest` populates a row; `make api` returns it.

**M2 — Backend API + first frontend page (2-3 weeks)**
- All endpoints stubbed; wire SEC, FRED, EIA, Comtrade, eGRID, Form 4.
  Score recompute job. Next.js scaffold with `/` scoreboard + `/segment/[slug]`
  drilldown using real data.
- Exit: navigate scoreboard → segment → top ticker with charts.

**M3 — Screener, thesis notes, polish (1-2 weeks)**
- Screener filters, thesis editor, horizon toggle, refresh schedule live
  on launchd.
- Exit: daily-refreshed dashboard, three conviction baskets on `/`.

**M4 — Iterate (ongoing)**
- Backtest scores against 12-18mo hindsight; refine weights; consider
  paid data upgrade; Postgres cutover if perf demands.

---

## 9. Risks & open questions

**Likely to bite:**
- *EDGAR rate limits + flaky full-text search.* Cache aggressively;
  fall back to local-downloaded `data.sec.gov` submissions index.
- *EIA v2 API changes.* Pin API version; snapshot responses.
- *Forward-looking statements in 10-Ks are noisy.* Pull from management
  guidance (not analyst recaps), weight by disclosing-executive seniority.
- *Single-vendor methodologies (HBM, CoWoS) make "tightness" lumpy.*
  Smooth with 3-month MA; document the choice.

**Genuine open questions (parking lot for later):**
- Sell-side research ingestion — wait until the score has a real
  conviction track record, then justify paid data.
- Backtest depth — at least 12-18 months of signal history needed before
  any weight is trusted.

---

## 10. Ontology (`research/05_ontology/`)

The value chain map, the universe, and the segment brief cross-references
all collapse into a single OWL ontology. Three layers:

### 10.1 Core vocabulary (TBox — the schema)

**Top-level classes (small set, then specialize):**

- `owl:Thing`
  - `Sector` (abstract container; rarely instantiated directly)
    - `HardwareSector` — front-end equip, fabs, packaging, HBM, networking, GPU/ASIC, systems, rack-scale, IDC shell
    - `InfrastructureSector` — power generation, transformers, T&D, cooling/water
    - `MaterialsSector` — raw inputs, semiconductor materials
    - `DownstreamSector` — inference / neoclouds / enterprise SaaS
  - `Company` (instance-only; never subclassed)
  - `GeographicRegion` — `NorthAmerica`, `Europe`, `GreaterChina`, `Japan`, `Korea`, `Taiwan`, `SoutheastAsia`, `MiddleEast`
  - `Commodity` — helium, neon, palladium, uranium, water, electrical steel, etc.

**Why "Sector" instead of "Segment":** the user noted that the boundary
between a class and an instance is ambiguous in supply chains. A *sector*
is a class (a category of firms). A *company* is an instance. A *role* is
also a class (`Foundry`, `IDCOperator`, `GPUDesigner`) and a company can
participate in multiple roles via `playsRole`. The role/sector split is
load-bearing: it lets one company (TSMC) play both `Foundry` and `OSAT`
without forcing it to be two individuals.

**Roles (a company plays one or more):**

- `Role`
  - `Manufacturer`
    - `Foundry` (TSMC, Samsung Foundry)
    - `IDM` (Intel, Samsung Memory, Micron, SK hynix)
    - `FablessDesigner` (NVDA, AMD, AVGO, MRVL)
    - `OSAT` (ASE, Amkor, JCET, Powertech)
    - `EquipmentMaker` (ASML, AMAT, LRCX, KLAC, Tokyo Electron, ASMPT)
    - `MaterialsSupplier` (Shin-Etsu, Sumco, JSR, Linde, Entegris)
    - `PowerEquipmentOEM` (GEV, Siemens Energy, Mitsubishi Heavy, BWXT)
    - `ElectricalEquipmentMaker` (HUBB, Eaton, Schneider, Hitachi Energy)
  - `InfrastructureOperator`
    - `Utility` (NEE, SO, DUK, Iberdrola, Enel)
    - `IDCOperator` (EQIX, DLR, AMT, IRM, CCI; plus hyperscalers as `SelfBuildIDCOperator`)
    - `WaterUtility` (municipal — instances, not always public)
  - `Integrator`
    - `SystemOEM` (SMCI, Dell, HPE)
    - `ODM` (Quanta, Wistron, Foxconn)
    - `RackIntegrator` (NVDA, GRC, Vertiv, Schneider)
  - `DownstreamConsumer`
    - `Hyperscaler` (MSFT, GOOG, AMZN, META)
    - `Neocloud` (CRDO, NBIS, plus private)
    - `EnterpriseSaaSConsumer` (instance only when the relationship is in scope)

**Object properties (the relations — the supply chain structure):**

- `supplies` (domain: `Role`, range: `Role`) — `subPropertyOf`: a `Foundry`
  supplies a `GPUDesigner`. Declare once, infer the inverse.
- `suppliesCommodity` (domain: `Role`, range: `Commodity`)
- `dependsOnCommodity` (domain: `Role`, range: `Commodity`)
- `playsRole` (domain: `Company`, range: `Role`) — many-to-many
- `headquarteredIn` (domain: `Company`, range: `GeographicRegion`)
- `operatesIn` (domain: `Role`, range: `GeographicRegion`)
- `hasExposureTo` (domain: `Company`, range: `Role`, with `exposure_pct`
  data property; this is the one dataproperty-on-an-edge case OWL allows)
- `competesWith` (domain: `Company`, range: `Company`, symmetric)
- `isAlternativeTo` (domain: `Role`, range: `Role`) — for substitution
  analysis; if role X has no `isAlternativeTo` then it's a single-source
  chokepoint
- `regulates` (domain: `GovernmentBody`, range: `Role`) — FERC, BIS, EU
  Commission, etc.
- `hasTicker` (domain: `Company`, range: `xsd:string`)

**Datatype properties (the obvious ones — per the user):**

- `hasExchange` (NYSE, NASDAQ, TSE, KRX, TWSE, FRA, …)
- `hasCurrency` (USD, JPY, KRW, TWD, EUR, …)
- `hasMarketCap` (USD-normalized decimal)
- `hasCurrencyHedge` (free-text ticker of the intended hedge instrument,
  or `null`)
- `isPublic` (xsd:boolean)
- `isLargeOrMidCap` (xsd:boolean, derived: `hasMarketCap >= 2e9`)

**Inheritance / class hierarchy semantics:**

- A `FablessDesigner` is a subclass of `Manufacturer`, so anything said
  about `Manufacturer` (e.g. `hasCapexIntensity`) is inherited.
- A `SelfBuildIDCOperator` is a subclass of both `IDCOperator` and
  `Hyperscaler` (multiple inheritance). OWL handles this — the reasoner
  will infer that MSFT is a `Hyperscaler ∧ IDCOperator`.
- `subClassOf` axioms encode the "is-a" rules: `Foundry ⊑ Manufacturer`,
  `OSAT ⊑ Manufacturer`, `GPUDesigner ⊑ FablessDesigner ⊑ Manufacturer`.

### 10.2 Instances (ABox — the data)

Loaded from `research/05_ontology/instances.ttl` (Turtle). **Generated
from** `02_universe.csv` and `00_value_chain.mmd` by a one-shot script
in `src/bottlewatch/jobs/build_ontology.py`. The CSV is the human-edited input;
the `.ttl` is generated. Re-running the build is part of the weekly
consistency job so the ontology stays in sync with universe changes.

Example assertions:

```turtle
:TSMC a :Company ;
    :hasTicker "TSM" ;
    :playsRole :TSMC_FoundryRole, :TSMC_OSATRole ;
    :headquarteredIn :Taiwan ;
    :hasMarketCap "550e9"^^xsd:decimal .

:TSMC_FoundryRole a :Foundry ;
    :operatesIn :Taiwan, :USA_Arizona, :Japan_Kumamoto ;
    :supplies :Nvidia_GPUSiliconRole, :AMD_GPUSiliconRole, :Broadcom_ASICRole ;
    :dependsOnCommodity :Helium, :Neon, :ProcessGases, :UltraPureWater .

:NVIDIA a :Company ;
    :hasTicker "NVDA" ;
    :playsRole :Nvidia_GPUSiliconRole, :Nvidia_NetworkingRole, :Nvidia_RackIntegratorRole .
```

A single company can `playsRole` in three distinct roles — and the
scoring engine treats each role's supply chain independently when
computing exposure.

### 10.3 Tools & storage

- **Authoring:** Protégé for the TBox (class hierarchy, properties).
  Manual, infrequent edits.
- **Storage:** Turtle files in `research/05_ontology/` for the source of
  truth. Loaded into an **in-process `owlready2` world** (Python) for the
  API server. `owlready2` is sync and fast for graphs in the thousands of
  individuals — well within our 100-150 company scale. No external
  triplestore (Fuseki/Jena) for v1; promote later if we need concurrent
  SPARQL endpoints.
- **Reasoner:** **HermiT** (shipped with `owlready2`) for class
  consistency and transitive inference (transitive `supplies`).
- **Queries:** SPARQL via `owlready2`'s SPARQL engine. Every dashboard
  endpoint translates to SPARQL under the hood.

### 10.4 How the ontology replaces existing artifacts

| Old artifact | New home |
|---|---|
| `02_universe.csv` | SPARQL against `:Company` + `:playsRole` + `:hasExposurePct` |
| `00_value_chain.mmd` (manual mapping) | SPARQL against `:Role ⊑ :Sector` + `supplies` relations |
| Segment briefs → which tickers | SPARQL: `?c :playsRole [a :Foundry] ; :hasExposurePct ?pct` |

The CSV is **kept as a human-edited input** — easier to review in a
spreadsheet than Turtle — but is the build input, not the runtime source.

### 10.5 How the ontology drives the dashboard

**Replace universe CSV** — `/v1/tickers` becomes a SPARQL query
(`SELECT ?ticker ?name ?segment ?exposure WHERE …`). Filter params
translate to SPARQL `FILTER` clauses.

**Feed scoring engine** — the §7 formula's sub-scores are partly computed
from the ontology:

- `geo_concentration`: SPARQL aggregation
  `SELECT ?role (COUNT(DISTINCT ?region) AS ?n) WHERE { ?role :operatesIn ?region }`
  → low `n` = concentrated = higher bottleneck score
- `supplier_substitutability`: SPARQL
  `SELECT ?role (COUNT(DISTINCT ?alt) AS ?alts) WHERE { ?role :isAlternativeTo ?alt }`
- `supply_path_depth`: SPARQL property path
  `supplies/supplies/supplies+` for transitive depth from any node to
  `Hyperscaler`
- `regulatory_friction`: SPARQL
  `?regulator :regulates ?role` joined with a manually-curated friction
  rubric table

**Power /map page interactions** — clicking a node runs:

- Upstream: `SELECT ?supplier WHERE { :NodeRole ^:supplies/:supplies* ?supplier }`
- Downstream: `SELECT ?customer WHERE { :NodeRole :supplies/:supplies* ?customer }`
- Companies: `?c :playsRole :NodeRole ; :hasTicker ?ticker ; :hasExposurePct ?pct`
- Color: bottleneck score from §7, which itself reads from the ontology

### 10.6 Why this matters for the investor thesis

Three concrete payoffs:

1. **Transitive risk surfaces automatically.** If neon supply tightens in
   Ukraine, the reasoner + SPARQL can answer "which GPU/ASIC designers
   are exposed to a TSMC supply disruption" in one query — no manual
   mapping required.
2. **Single source of truth for "what counts as adjacent."** Whether GE
   Vernova belongs in the universe is now a class-membership question
   (`a :PowerEquipmentOEM`), not a hand-maintained column.
3. **The scoring is auditable.** Every score is reproducible from
   `(ontology, signals, methodology)` — no hidden state.

### 10.7 Concrete v1 deliverables for the ontology (M0 addendum)

- `research/05_ontology/bottlewatch.owl` — Protégé-authored TBox
  (class hierarchy + properties; ~50 axioms)
- `research/05_ontology/instances.ttl` — generated ABox (one-time
  bootstrap from the universe CSV and value chain map; updated by
  `build_ontology.py`)
- `src/bottlewatch/app/services/ontology.py` — `owlready2` wrapper exposing
  SPARQL queries as typed methods (`get_companies_in_role(role)`,
  `get_supply_path(from_role, to_role, max_depth)`, etc.)
- `src/bottlewatch/jobs/build_ontology.py` — CSV + Mermaid → Turtle builder;
  run on universe change and once per week as a consistency check
- Reasoning consistency check: `pytest` calls `world.reasoner.run()` on
  test fixtures and asserts the expected inferred class memberships

---

## Critical files

- `research/00_value_chain.mmd` — canonical hand-edited chain.
- `research/00_value_chain.json` — parsed DAG for React Flow.
- `research/05_ontology/bottlewatch.owl` — TBox (schema).
- `research/05_ontology/instances.ttl` — ABox (data).
- `src/bottlewatch/app/services/ontology.py` — SPARQL wrapper.
- `src/bottlewatch/jobs/build_ontology.py` — CSV + Mermaid → Turtle.
- `research/04_scoring_methodology.md` — defensibility lives here.
- `src/bottlewatch/app/ingest/__init__.py` — adapter contract.
- `src/bottlewatch/jobs/refresh_daily.py` — daily pipeline entry point.

---

## Verification (end-to-end test)

1. `make research` produces `research/00_value_chain.svg`,
   8-12 segment briefs, populated `02_universe.csv`, the
   ontology (`bottlewatch.owl` + `instances.ttl`), and the scoring doc.
2. `make ingest` (or `uv run python -m backend.jobs.refresh_daily`) writes
   rows to `data/processed/bottlewatch.db` from at least 3 sources.
3. `make ontology` runs `build_ontology.py` and the HermiT reasoner
   passes consistency checks (no unsatisfiable classes, all `:Company`
   instances have a `:hasTicker`).
4. `make api` starts uvicorn; `curl localhost:8000/v1/scores` returns
   the scoreboard with at least one segment scoring > 50.
5. `make web` starts Next.js on `:3000`; `/` shows the scoreboard,
   `/segment/<slug>` shows real charts, `/tickers` screener filters work,
   `/map` shows the navigable DAG with colored nodes, and clicking a
   node opens the company panel (populated from SPARQL) and "drill
   upstream" recenters the graph on that node.
6. Manual smoke: pick a segment, drill to a ticker, confirm the
   exposure % matches `02_universe.csv` and at least one lead-indicator
   chart has data. Pick a commodity (helium), confirm the SPARQL query
   returns the expected chain of dependent roles.
7. Schedule check: confirm `launchd` plist is loaded (`launchctl list | grep bottlewatch`)
   and `data/cache/refresh.log` shows the next-day run.