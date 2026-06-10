# bottlewatch

A two-tier dashboard for a solo investor monitoring the **AI supply
chain** — surfacing *binding bottlenecks* and the public companies
exposed to them. **Investment-first**, not educational.

The headline thesis: a static "what's tight right now" scoreboard is
consensus-priced by the time you see it. **Edge lives in predicting
trajectory** — which bottlenecks are *emerging* (proactive long), which
are *peaking* (momentum long or trim), and which are *resolving* (short
or skip; **never long**). See [the plan](docs/plans/2026-06-03-bottlewatch-v1.md)
for the full design.

## Status — M0–M4 complete

The full M0–M4 pipeline is delivered and end-to-end verified. M0
delivered the **30-min read-through** of the AI supply chain
investment thesis, with every segment, ticker, and scoring
assumption backed by a citation:

- [Value chain map](research/00_value_chain.md) — Mermaid DAG covering
  materials → fabs → packaging → HBM → networking → GPU/ASIC → systems
  → rack-scale → IDC shell → power → cooling → inference, with one
  supplier-of-supplier step upstream of every node.
- [11 segment briefs](research/01_segments/) — definition, demand drivers,
  supply side, chokepoints, public players, lead indicators, **momentum**,
  **resolution ETA**, and **regime call** (EMERGING / PEAKING / PEAKED /
  RESOLVING / STABLE) for each.
- [Investable universe](research/02_universe.csv) — 131 tickers across
  ~25 local listings, with per-ticker regime-risk annotations.
- [Data sources assessment](research/03_data_sources.md) — 10 free
  sources (SEC EDGAR, EIA, FRED, Comtrade, eGRID, Form 4, …) ranked by
  signal/noise for the bottleneck thesis.
- [Scoring methodology](research/04_scoring_methodology.md) — formula,
  regime/ETA/guard model, two worked examples (RESOLVING + EMERGING).
- [Ontology](research/05_ontology/) — OWL TBox (96 axioms, 11-commodity
  enumeration) + NT ABox (128 companies, 131 reified per-role exposures),
  validated by HermiT.

The scoring and regime model is also encoded in
[the plan §7.6-7.8](docs/plans/2026-06-03-bottlewatch-v1.md#7-conviction-scoring-v1-formula).

**M1–M4** built the operational stack on top: SQLite + alembic
schema, 8 ingest adapters (EIA v2, EIA capacity, EIA 860M, EIA
electric, FRED, Comtrade, eGRID, SEC EDGAR, SEC insider Form 4),
a daily orchestrator with progress bar and cadence-based
watermarks, a FastAPI surface (segments, scoreboard, ticker
detail, map, screener, thesis notes, score history), a Next.js
15 dashboard, scheduled `launchd` jobs, and a 2-year backtest
of the scoring model.

## Project layout

```
bottlewatch/
├── pyproject.toml        # hatchling, Python 3.13, src/ layout
├── Makefile              # sync, ontology, validate-ontology, ingest, api, web
├── src/bottlewatch/      # the package
│   ├── jobs/             # one-shot CLIs (build, validate, refresh)
│   ├── app/              # FastAPI app (M1+)
│   └── tests/            # pytest (M1+)
├── research/             # M0 deliverables (markdown, csv, ontology)
├── data/                 # raw / processed / cache (gitignored)
├── docs/                 # plans, ADRs
├── frontend/             # Next.js 15 dashboard (M2+)
└── notebooks/            # exploratory analysis
```

## Quick start

```bash
# 1. install the package (editable) + dependencies
make sync

# 2. build the ontology ABox from the universe CSV + value chain JSON
make ontology
#   → research/05_ontology/instances.ttl

# 3. run HermiT + sample SPARQL queries against the ontology
make validate-ontology
#   [PASS] reasoner
#   [PASS] class consistency
#   [PASS] companies have ticker  (128 companies checked)
#   [PASS] geo_concentration, supply_path_depth, NVDA role-mates
```

## Make targets

| Target | What it does |
|---|---|
| `make sync` | `uv sync` — install the editable package + dev group |
| `make ontology` | Build the ABox from CSV + JSON via the `bottlewatch-build` console script |
| `make validate-ontology` | Run HermiT + SPARQL checks via the `bottlewatch-validate` console script |
| `make ingest` | Daily data refresh (M1; `bottlewatch-refresh` console script) |
| `make api` | uvicorn the FastAPI app (M1+) |
| `make web` | `pnpm dev` for the Next.js dashboard (M2+) |
| `make research` | `ontology` + `validate-ontology` — the M0 verification loop |

## Roadmap

All milestones are delivered. Future work (M5+) is in the
`m4-backtest-final.md` next-steps section — automating
`transformers_tnd` from FRED PPI, geo-concentration via
SPARQL, web-UI sparklines.

- **M0** — Research report + ontology + scoring model. ✅
- **M1** — Pipeline skeleton: SQLite schema, EIA v2 adapter, daily
  refresh, alembic init. ✅
- **M2** — FastAPI endpoints, Next.js scoreboard, drilldown with real
  charts. ✅
- **M3** — Screener, thesis notes editor, multi-horizon toggle, live
  refresh on `launchd`. ✅
- **M4** — Backtest scores against 12-18mo hindsight; refine weights;
  Postgres cutover if perf demands. ✅
- **M5** — Sparkline charts (batched score history API + UI), FRED
  `A35SNO` for `transformers_tnd.demand_signal`, ontology-derived
  HHI for all 10 segments' `geo_concentration`. ✅

## License

Private; not for distribution.
