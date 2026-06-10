# Data Sources Assessment — Bottlewatch v1

> Per the v1 plan (§6), 7 sources are in scope. Each is assessed on:
> cost, API key, rate limits, freshness, historical depth, known gotchas,
> and fallback. Final section: which 2-3 to wire first for M1 (pipeline
> skeleton) and which to defer.

Source list and ordering is the plan's §6 ranking by signal/noise. This
document goes one level deeper — for each source, what specifically to
ingest, what fields to extract, and the realistic edges.

---

## 1. SEC EDGAR full-text search (`efts.sec.gov`)

**What we pull from it:** 10-K/10-Q capacity language, capex line items,
customer concentration, and 8-K capacity announcements. Specifically:
the `full-text-search` endpoint with a query like
`"lead time" OR "CoWoS" OR "backlog" OR "capacity"`, filtered to
CIK/forms in our universe. Index queries by `ticker` (mapped from CIK
in `submissions`) and by `segment_kw` (mapped from the segment's
vocabulary — e.g. for `transformers_tnd` we match `"transformer"`,
`"switchgear"`, `"EHV"`, `"GOES"`).

**Free?** Yes. Public US-government data.
**API key required?** No.
**Rate limits:** Per SEC fair-access policy, **10 requests/second,
max 600 in any 10-minute window** for the full-text endpoint. The
submissions endpoint (`data.sec.gov/submissions/CIK*.json`) is more
restrictive — roughly the same per-user aggregate. Practical ceiling
with politeness: ~5 req/sec sustained, with a token-bucket limiter.
**Freshness:** 10-Ks filed within minutes of the SEC accepting the
filing (typically same-day, occasionally T+1). 8-Ks real-time.
**Historical depth:** Full-text back to 2001 (EDGAR FT launch);
structured submissions JSON back to ~2017 reliably.
**Known gotchas:**
- The full-text search returns *hits* with form type and date, not
  parsed text. The follow-up is `Archives/edgar/data/{cik}/{accession}`
  walking, then parsing XBRL. This is the most engineering-intensive
  adapter.
- Forward-looking statements are noisy; the plan calls for filtering
  to "Item 1. Business" + "Item 7. MD&A" + "Risk Factors" sections,
  weighted by disclosing-executive seniority.
- Some filers (foreign private issuers like TSMC's 20-F, ASE) report
  differently; `forms=20-F` and `forms=6-K` need explicit inclusion.
- EDGAR occasionally rate-throttles anonymous users harder than
  documented. Mirror with the bulk `data.sec.gov` submissions index
  for the daily refresh.

**Fallback plan:** (a) cache aggressively (Turtle + parquet snapshots
in `data/cache/edgar/`); (b) for any ticker whose 10-K is hard to
parse, fall back to the IR website PDF; (c) for the daily refresh,
prefer the `submissions` JSON (small, structured) over `efts.sec.gov`
scans (large, noisy).

**Signal density per unit effort:** Highest. This is the primary
source for "what does management actually say about lead times and
capacity" — which is the load-bearing input to two of our five
sub-scores (lead_time_growth, capacity_tightness).

**Where to start in v1:** begin with the
`submissions/CIK*.json` polling for form-type triage, then add
`efts.sec.gov` queries scoped to the 25 largest universe tickers
(first-pass). Full sweep in M3.

---

## 2. EIA Open Data v2 (`api.eia.gov/v2`)

**What we pull:** US electricity demand (load by balancing
authority), generation by fuel type, retail sales by sector, and
forward-looking STEO (Short-Term Energy Outlook) projections. Series
IDs of immediate use:
- `ELEC.GEN.ALL-{US}-{hourly}` — US total net generation, hourly
- `ELEC.SALES.TX-RES-M` — retail sales (residential sample)
- `ELEC.CAP.A` — net summer capacity by energy source
- `ELEC.PRICE.{US}-ALL.M` — average retail price
- `STEO.PAPR.US.M` — STEO projected total electricity generation

**Free?** Yes.
**API key required?** Yes — free, email signup at
<https://www.eia.gov/opendata/>. Stored in env as `EIA_API_KEY`.
**Rate limits:** Documented at "unlimited for non-commercial" but
practically throttled to ~5000 requests/hour. The real constraint is
the row cap per request (~5000 rows); for hourly US data this means
slicing by month.
**Freshness:** Hourly within ~2 hours of observation; STEO monthly
(released ~10th of the month); generation by fuel monthly (~2 months
after period end).
**Historical depth:** Hourly back to ~2015; monthly back to 2001.
**Known gotchas:**
- Hourly US-all rollups are massive; for a single dashboard view
  prefer daily/weekly aggregations.
- The `v2` API has had breaking schema changes; pin the API version
  in the URL and snapshot responses.
- The v2 "facets" parameter is powerful but confusing — start with
  `frequency`, `data[0]`, `start`, `end`, `sort[0][column]`, `sort[0][direction]`.
- Balancing authority codes (`BA`) differ from utility IDs and from
  NERC region codes; you need a lookup table. EIA publishes one.

**Fallback plan:** (a) for any series that 5xxs, retry with
exponential backoff (max 3 attempts), then mark as `stale` and
serve the last good value with a `stale_since` flag. (b) For US
hourly load, the EIA-930 file on the `Open Access Same-Time
Information System (OASIS)` is more granular — use as secondary.

**Signal density:** Highest for the power-bottleneck thesis
(plan §6 names this "headline source"). Drives the `demand_signal`
sub-score for the power/transformer/utility segments.

**Where to start:** first adapter end-to-end (plan §8 M1: "start
with EIA"). The API is well-documented, the data is small, and the
use cases are concrete.

---

## 3. EIA-860 / 860M (generator inventory)

**What we pull:** The annual EIA-860 and monthly EIA-860M generator
inventory. Fields of immediate use: `Entity ID`, `Plant ID`, `Prime
Mover` (`CA`, `CT`, `ST`, `CC`, `GT` for combustion turbine / combined
cycle / gas turbine), `Energy Source Code` (`NG`, `NUC`, `WND`, `SUN`),
`Nameplate Capacity (MW)`, `Operating Year`, `Planned Retirement Year`,
`Status` (`OP`, `OS`, `SB`, `TS` for operating/standby/standby-shelved/
under-construction). Each row is a generator unit.

**Free?** Yes — direct download from
<https://www.eia.gov/electricity/data/eia860/>. Excel + zipped CSV.
**API key required?** No.
**Rate limits:** None (file download, not API). No throttling needed
beyond a single GET with retry.
**Freshness:** EIA-860 released annually (early Q3, covering prior
year); EIA-860M released ~monthly. Both with ~1-2 month reporting lag.
**Historical depth:** EIA-860 back to 2001; pre-2010 limited.
**Known gotchas:**
- File format churns year-to-year (new columns, renamed columns).
  Build a normalizer that maps per-version.
- `Operating Year` is the *original* year — what we want for
  "fleet age" is `Initial Operation to Power System` (newer column
  name varies). Verify with the schema doc.
- "Planned" additions are notoriously optimistic — the median delay
  from `Status=TS` to `Status=OP` is ~3-5 years for gas turbines, ~7-10
  years for nuclear. Treat `TS` counts as a leading indicator with a
  haircut.
- Generator entries with `Prime Mover=BA` (battery) are growing fast
  and were barely reported pre-2018; backfill is partial.

**Fallback plan:** None needed. The file is a one-shot download; if
EIA ever stops publishing, the FERC EIA-411 (`Electric Power
Capacity` filings) is a partial substitute but with much worse
granularity. There is no online API; we cache the raw zips in
`data/cache/eia860/` keyed by release month.

**Signal density:** Drives `capacity_tightness` (orders-to-capacity
ratio proxy) and `geo_concentration` (US state + NERC subregion mix)
for the `power_generation_oem` and `transformers_tnd` segments.

**Where to start:** M2 (after EIA v2 is wired and the daily refresh
scaffolding works). Update cadence: monthly ingestion of 860M; annual
ingestion of 860.

---

## 4. FRED (`api.stlouisfed.org`)

**What we pull:** US macroeconomic context for cross-validation of
demand signals. Series of immediate use:
- `INDPRO` — Industrial Production: Total Index
- `TCU` — Capacity Utilization: Total Industry
- `IPG3364S` — IP: Semiconductors
- `WPU31132506` — PPI: Semiconductors
- `WPU1321` — PPI: Transformers and power regulators
- `WPU106301` — PPI: Turbines and turbine generator sets
- `WPU1134` — PPI: Electrical machinery and equipment
- `PCU334413334413` — PPI: Semiconductor machinery mfg
- `NAPM` (deprecated) or `MANEMP` / `NEWORDER` — ISM / Mfg PMI proxies
- `DGS10`, `DGS2`, `T10Y2Y` — rates and curve
- `BAMLH0A0HYM2` — high-yield credit spread
- `CSUSHPISA` — Case-Shiller home prices (less load-bearing)

**Free?** Yes.
**API key required?** Yes — free signup at
<https://fred.stlouisfed.org/docs/api/api_key.html>. Stored as
`FRED_API_KEY`. The `fredapi` Python wrapper is a clean fit.
**Rate limits:** 120 requests/minute, sustained. Comfortable.
**Freshness:** Daily for DGS series; monthly for IP/PPI (release
~mid-month for the prior month). FRED posts revisions; pull a 3-day
release window to catch them.
**Historical depth:** Varies; IP back to 1919, PPI back to 1913,
DGS back to 1962.
**Known gotchas:**
- Series IDs are case-sensitive and silently 404 on typos — verify
  with `fredapi`'s `search()` before committing.
- PPI subseries (`WPU31*`) are volatile; normalize YoY not MoM.
- ISM (`MANPMI` or `NAPM`) is the *real* signal but isn't on FRED —
  ISM is a private publication. Substitute with the Markit PMI
  (`Mfg PMI: TX` etc.) or the regional Feds (Dallas, Philly, NY).
  **Open question** for v2: direct ISM subscription.
- FRED adds series with non-obvious seasonal adjustment; the
  `seasonally_adjusted` flag in the metadata is the source of truth.

**Fallback plan:** (a) for any 4xx/5xx, exponential backoff + cache;
(b) for ISM specifically, scrape the regional Fed surveys (Dallas,
Philly) as proxies until/unless we get a paid ISM feed.

**Signal density:** Medium. FRED doesn't *directly* answer the
bottleneck question but contextualizes `demand_signal` (PMI surge
→ "expanding"; PPI spike → "price pressure"). It also lets us
reject false positives ("lead times rose because end-market
demand collapsed").

**Where to start:** M2. Easy to wire, low engineering cost. Use as
a secondary input to `demand_signal` after the primary (hyperscaler
capex, IDC pre-lease) is in place.

---

## 5. UN Comtrade (`comtradeapi.un.org`) + USITC DataWeb

**What we pull:** Bilateral trade flows under specific HS codes. The
binding codes:
- **HBM**: there's no clean HS code for HBM specifically. Most HBM
  ships under `8542.32` (Electronic integrated circuits, MOS).
  Cross-reference with `8541.10` (LEDs) for the more specialized
  memory products. **Open question** for v2: ComtradePlus has a
  finer taxonomy; we may need a "Chips IP" (custom code) workaround.
- **Lithography equipment**: `8486.20` (Machines for the manufacture
  of semiconductor devices).
- **Transformers**: `8504.21` (Liquid dielectric, ≤650 kVA),
  `8504.22` (>650 kVA but ≤10,000 kVA), `8504.23` (>10,000 kVA).
  The large-power class is `8504.23`.
- **Semiconductor manufacturing equipment (catch-all)**:
  `8486.10` through `8486.40`.
- **Power semiconductors** (IGBT, SiC): `8541.40` or `8541.49` (we'll
  refine during adapter build).

For each: pull `reporter=MMR046` (world totals), `partner=156` (China),
`partner=410` (South Korea), `partner=158` (Taiwan), `partner=392`
(Japan), `period=YYYYMM`, `flow=M` (import into the partner) or
`X` (export from the reporter). Mirror with USITC for US-side
data quality.

**Free?** Comtrade free tier is yes; the standard `comtradeapi.un.org`
endpoint is unrestricted for non-commercial use. USITC DataWeb
requires a free login.
**API key required?** Comtrade: no key, but rate-limited. USITC:
free, requires account.
**Rate limits:** Comtrade 100k requests/day on the standard
endpoint; **100 requests/10 seconds** in bursts. USITC has no
hard limit but session-based — limit to 1 req/sec sustained.
**Freshness:** Comtrade monthly with ~6-8 week reporting lag (varies
by partner). USITC DataWeb typically 4-6 weeks.
**Historical depth:** Comtrade back to 1962 (annual) or 2010
(monthly). USITC: similar.
**Known gotchas:**
- HS code revisions: the HBM "code" jumped classification in
  HS2017 → HS2022; the time series needs a bridge.
- Reported values are CIF (cost+insurance+freight) for imports,
  FOB for exports — never mix.
- Korean and Taiwanese reporting on advanced semis is *very*
  incomplete — they report generic "8523.*" for the bulk. Mirror
  with `World → Korea` from a Western partner for a more accurate
  read on actual HBM movements.
- HBM specifically is reported as "DRAM" in trade data; we have to
  infer from the unit price (HBM ASP is ~5-10x commodity DRAM) and
  partner mix. This is a model, not a query.

**Fallback plan:** (a) if Comtrade is down, use the World Bank
WITS export (re-packaged Comtrade with same source data). (b) for
HBM specifically, use SK hynix + Samsung reported quarterly
shipment data (in IR decks) as a top-down cross-check.

**Signal density:** High for the cross-border read on
`transformers_tnd` (China exports to US), `gpu_asic_silicon`
(SemiEquip trade), and `advanced_packaging` (OSAT is mostly
intra-Asia; we watch flows between Taiwan → Korea → US).

**Where to start:** M2. The endpoints are well-documented but
the HBM inference is non-trivial; budget more engineering time
than FRED.

---

## 6. EPA eGRID / EJSCREEN

**What we pull:** Subregional emissions and water-stress overlays
for IDC siting. eGRID is the headline; EJSCREEN adds environmental
justice / community-impact overlays that are a leading indicator
of permitting friction.

**eGRID**: downloadable Excel/ZIP from
<https://www.epa.gov/egrid>. Releases every 2 years; eGRID 2024
expected mid-2025 (eGRID 2022 latest as of writing). Fields:
`SUBRGN` (eGRID subregion), `ORISPL` (plant ID), `PLNAME` (plant
name), `PLFUELCT` (primary fuel), `CAPFAC` (capacity factor),
`GENATN` (annual generation), `NOXRATE`, `CO2RATE`, `HGRATE` (per
MWh emissions), `WATER_TYPE` (cooling water source).

**EJSCREEN**: download-by-block-group CSV/GeoDB from
<https://www.epa.gov/ejscreen>. Releases every 2-3 years; EJSCREEN
2024 is current. Fields: `ID` (block group FIPS), `PM25`, `OZONE`,
`TRAFFICSCORE`, `LEAD`, `WATERSCORE` (drinking water indicator),
`RESPTSCORE`, `NPL_SCORE` (proximity to Superfund sites).

**Free?** Yes.
**API key required?** No.
**Rate limits:** None (file download).
**Freshness:** eGRID biennial, ~12-18 month lag from reference year
to publication. EJSCREEN biennial. Both are *slow*.
**Historical depth:** eGRID back to 1996 (but useful data from
~2005). EJSCREEN back to 2014.
**Known gotchas:**
- eGRID subregions (`SUBRGN`) are *not* the same as balancing
  authorities, FERC regions, or ISO footprints. Build a lookup.
- eGRID's per-plant water-use column has been spotty; recent
  editions are better. For water-stress overlays, use EJSCREEN's
  `WATERSCORE` (drinking water indicator, not direct data center
  water use) or the WRI Aqueduct dataset.
- The file is large (~250MB unzipped for full eGRID); load with
  polars in `LazyFrame` mode.
- "Subregion" naming is occasionally revised between editions.

**Fallback plan:** (a) WRI Aqueduct for water stress (free CSV
download) is a stronger water-stress signal; include as a v2
addition. (b) For permitting friction, the v1 approach is
*manual* — we annotate each county with a permitting-friction
score (rubric of: moratorium list, PUCT/PUC docket backlog,
NERC alert) rather than scrape. This is what feeds
`regulatory_friction` and is acceptable for v1.

**Signal density:** Medium. eGRID is mostly used for *validation*
("is the data center in a low-carbon subregion?") rather than as
a leading indicator. It feeds the `regulatory_friction` sub-score
indirectly via the siting-rubric.

**Where to start:** Defer to M3. The file is huge, the
interpretation requires local context, and the binding
permitting signal is more easily curated than scraped.

---

## 7. SEC Form 4 insider filings

**What we pull:** Form 4 cluster buys/sells on universe tickers.
Specifically: every Form 4 with non-routine transaction code
(we filter out `S`/`D` for 10b5-1 plan trades) and look for:
- Three or more insiders buying in the same 30-day window
  (cluster buy signal — historically strong indicator per
  empirical literature)
- Same-ticker Form 4s with `transactionCode=F` (payment of
  exercise price or tax withholding) — exclude
- Same-ticker Form 4s with `transactionCode=P` (open-market
  purchase) or `M` (exercise of derivative) — keep
- $ value of purchase > 0.1% of the insider's total compensation
  (filter small noise)

**Free?** Yes.
**API key required?** No.
**Rate limits:** Same 10/sec limit as the rest of SEC. Comfortable.
**Freshness:** Form 4s filed within 2 business days of transaction
(US rule); the EDGAR feed surfaces them in real time.
**Historical depth:** Form 4 going back to 2002 on EDGAR FT.
**Known gotchas:**
- 10b5-1 plan trades dominate the dataset; the filter for
  "non-routine" requires the `transactionCode` plus a footnote
  flag. v1: filter on `transactionCode=P` only (open-market
  buy); v2: incorporate 10b5-1 detection via the plan-amendment
  Form 144.
- Form 4 data is structured XML — the SEC provides a `Form 4
  Schema` and there's a Python `edgar` package. Use the schema,
  not the XML directly.
- CEO/CFO trades are noisier than cluster trades from directors
  — weight equally in v1; consider weighting in v2.
- Reporting lag (2 business days) means this is a *lagging*
  signal by the time we see it. Cluster buys today may reflect
  knowledge from 3-5 days ago. Discount accordingly.

**Fallback plan:** (a) if EDGAR 4s are delayed, scrape
`OpenInsider` or use the WhaleWisdom free tier (we'd
rather not pay but the free API is decent). (b) For the
"smart money" angle, Form 13F (institutional holdings) is a
companion source — wire in v2 as `13f` adapter.

**Signal density:** High (per the plan's §6 ranking: "Free,
high-signal early indicator"). This is the *only* source
that provides a real-time sentiment signal on individual
tickers in the universe, and cluster buys in particular
have shown to be statistically robust leading indicators
in academic studies.

**Where to start:** M2. Easy to wire (small payload, structured
schema), high value per line of code. Plug in alongside the
EDGAR full-text adapter since the SEC infrastructure is shared.

---

## Recommendation: which 2-3 to wire first in M1

**Start with EIA v2 (#2) and the EIA-860M file ingestion (#3).**
These two give us the most direct view of the binding constraint
in the thesis (US power generation capacity vs. data center load
growth). EIA v2 is well-documented, free, and a small surface
area. EIA-860M is a file download — essentially no engineering.

**Add Form 4 (#7) as the third M1 wire** because the data is
small, structured, and the scoring methodology will want a
real-time signal from day one. The cluster-buy filter is a
20-line job once you have the Form 4 XML schema loaded.

**Defer to M2/M3:** EDGAR full-text (#1 — high value but
engineering-heavy), FRED (#4 — easy but secondary), Comtrade
(#5 — HBM inference needs care), and eGRID (#6 — file size
+ interpretation overhead).

**Rationale ordering summary:**

| Order | Source | Why this order |
|---|---|---|
| M1 | EIA v2 | Headline source for power thesis; small surface |
| M1 | EIA-860M | File download; generator inventory |
| M1 | Form 4 | Smallest payload; real-time signal |
| M2 | EDGAR full-text | Big value, big engineering; needs a parser |
| M2 | FRED | Easy, secondary signal |
| M2 | Comtrade / USITC | HBM inference is non-trivial |
| M3 | eGRID / EJSCREEN | File is huge; interpretation is local |

---

# Resolution ETA data sources (v2 regime model)

The regime/ETA model (per `04_scoring_methodology.md` §7) requires
three new classes of data on top of the seven v1 sources above:

1. **Capacity-additions / commissioning tracker** — when does the
   announced supply actually come online?
2. **Book-to-bill and lead-time trends** — the demand-side
   counter-signal: are the orders softening before the
   supply arrives?
3. **Hyperscaler capex guidance** — does the demand side still
   justify the bottleneck label, or is it cooling?

These are listed by **importance for v2**, with accessibility
for the dashboard at the end of each. The free-first ordering
matters because the v1 plan runs on a no-paid-API budget.

---

## 8. Capacity-additions / commissioning tracker (NEW for v2)

This is the single most important new source. The regime label
(`PEAKING` vs. `RESOLVING`) is decided almost entirely by *when
announced capacity actually commissions*. A segment with three
hyperscalers signing 5-year CoWoS-L allocations looks tight today
but is `RESOLVING` if TSMC's CoWoS ramp brings 90k+ wafers/month
online by mid-2026.

**The capacity add comes in three distinct shapes — the source
differs by shape.**

### 8.1 Power generation capacity

**Source: EIA-860M (already in v1 #3) for US.** Monthly file
with planned additions (`Status=TS`, "under construction"), with
operating month and nameplate capacity. The lag from `TS` to `OP`
varies by tech (gas turbine 3-5 years, nuclear 7-10 years, solar+
storage 1-2 years). We treat `TS` count as the leading indicator,
**discounted by historical delay percentiles**.

**Free?** Yes (already counted in #3).

**What we extract for v2:**
- `TS`-status generators with `Operating Year` in next 24 months
- by prime mover (CC/CT/BA/CA/ST) and by ISO/RTO region
- for the AI-demand regions specifically (PJM, ERCOT, SPP,
  MISO, SERC, CAISO)
- the "haircut" — median historical delay by tech, applied
  to the planned operating year

**Known gotchas:**
- ISO interconnection queue ≠ actual construction start.
  PJM alone has 2,500+ projects in queue; ~30-50% withdraw
  or are delayed. We use the queue as a *ceiling* and the
  860M `TS` count as the more committed subset.
- Permitting-driven delays are not in the data. We add a
  **permit buffer** of 6-12 months for any project that has
  not yet broken ground (see 04_scoring_methodology.md §7.4).

### 8.2 Semiconductor fab + packaging capacity

**Source: SEMI World Fab Forecast (WFF)** is the canonical
industry database. Captures fab construction announcements
(groundbreaking → equipment move-in → ramp → HVM), by node,
by product, by region, for the global industry. Released
quarterly.

**Free?** **No.** SEMI WFF is a paid subscription
(~$10-15k/year for a single-user license). We treat this as
a v2 add-on — not in v1 budget.

**Free alternatives (in priority order for v1):**
1. **TSMC, Samsung, SK hynix, Micron quarterly capex + capex
   guide** in earnings transcripts. We parse the relevant
   language ("FY26 capex of $X", "CoWoS wafer capacity
   expanding to Y wafers/month by Q4") and structure it
   manually into a per-vendor capacity-addition ledger.
2. **SEMI World Fab Forecast press releases** (free
   quarterly) — gives aggregate global wafer-add counts by
   region, not by node/product. Useful for top-down
   validation.
3. **Hyperscaler capex disclosure** (free) — when an MSFT
   or AMZN announces a $50B data center commitment, we know
   there's a downstream demand pull on the fab/packaging
   supply chain. This is the demand-side complement.
4. **TSMC Arizona / Kumamoto, Samsung Texas, Intel Ohio
   milestones** — public press releases + state-government
   subsidy filings. Free but manual.

**What we extract for v2:**
- Per-vendor capacity-addition ledger: (a) site, (b) product,
  (c) `start_equipment_move_in` date, (d) `HVM` date, (e) wafer/mo
  add at HVM, (f) confidence ("ground broken" / "under
  construction" / "announced only")
- A confidence-weighted total for each segment (e.g. "HBM
  capacity additions 2026-2027, with X confidence that 70%
  will hit HVM on schedule").

**Known gotchas:**
- **Groundbreaking announcements ≠ capacity.** A 2024
  groundbreaking routinely means 2027+ HVM, with delays.
- **Yield ramp is not in the data.** A new fab is in
  production (HVM) for 6-12 months before reaching
  nameplate capacity. We add a `yield_ramp_haircut` of
  ~30% for the first year of any new fab.
- **TSMC's N2 yield is a 2025-2026 swing variable** for
  advanced node; not in the public data.

### 8.3 Transformer manufacturing capacity

**Source: UEA (Utility Equipment & Analytics) / Wood Mackenzie
transformer database.** Captures LPT (>100 MVA) and
distribution transformer manufacturer capacity, by region and
vendor, with planned additions.

**Free?** **No.** Wood Mackenzie is paid (high 5-figure
subscription); UEA is mid-4-figure. Defer to v2 unless the
investor provides a license.

**Free alternatives:**
1. **Hitachi Energy, GEV, Siemens Energy, ETN earnings
   transcripts** — capacity expansion announcements.
2. **DOE Transformer Procurement / Strategic Transformer
   Reserve** — public RFPs and awards.
3. **Section 232 filings on transformer imports** —
   Federal Register.

**Known gotchas:**
- The 4-5 major LPT OEMs all have multi-year backlogs; the
  *announced* capacity is small (~20-40% over current
  levels, multi-year). This means transformer ETA is
  structurally 12-24 months.
- Hitachi Energy is private; the parent Hitachi (6501.T)
  consolidated reporting dilutes the LPT-specific capacity
  view.

### 8.4 Ranking for v1

For v1, we **start with the free alternatives and the EIA-860M
data we already have**, and treat the paid sources (SEMI WFF,
Wood Mackenzie) as a v2 upgrade if the regime/ETA model
proves load-bearing for conviction baskets.

The plan: build the capacity-additions ledger in a
`research/06_capacity_ledger.md` (manual spreadsheet-style
document) as a v1 stub, then automate the top-down aggregation
in v2 when we have a paid source or a scraper.

---

## 9. Book-to-bill and lead-time trends (NEW for v2)

The book-to-bill ratio is the *single best* demand-side
counter-signal: when orders stop being placed, lead times
collapse within 1-2 quarters, and the regime shifts from
`PEAKING` to `RESOLVING` *before* the new capacity actually
arrives. This is the early-warning half of the regime model.

### 9.1 SEMI book-to-bill (semiconductor front-end equipment)

**What we pull:** SEMI's monthly Book-to-Bill ratio for
North American semiconductor equipment manufacturers. The
ratio = (3-month bookings) / (3-month billings). A ratio
above 1.0 means orders > shipments = tightening; below 1.0
means softening.

**Free?** Yes — SEMI publishes the headline ratio and 3-month
moving average monthly at
<https://www.semi.org/en/products-services/market-data/
book-to-bill>.

**API key?** No. Web scrape (one URL, monthly update).

**Rate limits:** None (single GET). Refresh once a month.

**Freshness:** Released ~mid-month for the prior month's
data.

**Historical depth:** Back to 1991 (the historical record is
the longest-running semiconductor demand indicator).

**Known gotchas:**
- The North American book-to-bill is dominated by AMAT, LRCX,
  KLAC, TER, ASML (via US entity), TEL. It's a useful
  aggregate but doesn't break out by node or product.
- The ratio is volatile month-to-month; the 3-month MA is
  the right read.
- A book-to-bill above 1.0 is consistent with both `PEAKING`
  and `EMERGING` regimes; we cross-reference with absolute
  lead times (point 9.2) to disambiguate.

**Signal density:** High. This is the cleanest single
indicator of "is the demand for new fab equipment still
growing" — and by extension, "are the fabs being built that
will produce the 2027-2028 supply".

### 9.2 Lead times for transformers, gas turbines, and
specialty equipment

**Source: Wartsila, Siemens Energy, GE Vernova, Hitachi
Energy earnings transcripts and IR decks** for current
quoted lead times. Wood Mackenzie / UEA publish a
quarterly transformer lead-time index; we use the IR
language as the free source.

**What we extract:**
- Gas turbine heavy-duty lead time (months)
- Large power transformer lead time (weeks)
- HBM lead time (weeks; from SK hynix / Samsung / Micron
  earnings)
- CoWoS capacity utilization (qualitative; from TSMC)
- Switch ASIC lead time (from Broadcom, Marvell)
- Optical transceiver lead time (from COHR, LITE, Innolight)

**Free?** Yes — all in IR transcripts and 10-K risk factors.

**Known gotchas:**
- Companies don't always disclose lead times; when they do,
  the language is "approximately X months" and the precise
  value is judgment-call.
- The lead time can be sticky (companies stop reporting when
  it's no longer favorable) — a regime shift from
  `PEAKING` → `RESOLVING` may show as "we are not providing
  specific lead time guidance" before showing as a numerical
  decline. We watch for the *withdrawal* of language as a
  signal.

### 9.3 Ranking for v1

Wire the SEMI book-to-bill scrape (one URL, monthly). Add
the lead-time ledger as a manually-updated section of
`research/06_capacity_ledger.md`. Both are accessible for
v1.

---

## 10. Hyperscaler capex guidance (NEW for v2)

The demand-cooling signal. When MSFT/GOOG/AMZN/META guide
capex DOWN — or shift the *mix* away from AI infrastructure —
the bottleneck thesis weakens, even if supply hasn't arrived.

**Source: Earnings transcripts (8-K, 10-Q) from MSFT, GOOG,
AMZN, META, ORCL.** Capex is a single line in the cash flow
statement; the *narrative* on the earnings call is the
qualitative read on whether AI capex is still growing or
plateauing.

**What we extract:**
- Quarterly capex (USD, total + AI-specific when disclosed)
- Forward 4-quarter capex guidance (qualitative or range)
- Mix: AI capex as % of total capex
- Hyperscaler PPA announcements with nuclear / gas / renewable
  generators (proxy for "they are still building")
- The "demand cooling" signal: any 8-K language on capex
  pause, datacenter build deferral, or AI workload
  disappointment

**Free?** Yes — transcripts on investor relations sites and
Seeking Alpha. SEC EDGAR for the 8-K and 10-Q numbers.

**Rate limits:** None (manual scrape, monthly cadence).

**Freshness:** Quarterly (hyperscaler earnings calendar).

**Historical depth:** Transcripts back to ~2010 on Seeking
Alpha; SEC filings longer.

**Known gotchas:**
- Hyperscalers don't always break out AI capex separately
  from total capex. We default to "capex growth rate" as the
  proxy.
- Capex is *lumpy* (large one-time campus builds); the
  trailing 4-quarter rolling sum smooths this.
- "AI capex" is loosely defined; some companies include
  chips and some don't. We cross-reference with the IDC
  capex forecast (IDC publishes a quarterly update for a fee;
  the free press releases are the lower-fidelity alternative).

**Signal density:** Highest for the regime model. A
quarter-over-quarter capex *decline* or guidance cut is
the single most reliable leading indicator of a regime
shift from `PEAKING` → `RESOLVING`.

### 10.1 Ranking for v1

Highest priority. Free, accessible, and the load-bearing
input to the demand-cooling half of the regime model. We
propose a small hyperscaler capex tracker in
`research/06_capacity_ledger.md` (the same file as the
capacity additions ledger) — one row per quarter per
hyperscaler, with the capex number, AI share, and any
qualitative shifts.

### 10.2 Optional: sovereign AI capex ledger

The same logic applies to sovereign AI (Saudi HUMAIN, UAE
G42, EU EuroHPC, India AI Mission, Japan METI GenAI,
Korea Naver / NHN). Most announcements are public press
releases; we add a manual sovereign-AI ledger to the same
file. Free, but high-maintenance.

---

## Recommendation: which 2-3 of the NEW sources to wire first

**Start with hyperscaler capex guidance (#10)** — it's
free, has the cleanest source, and is the most direct
leading indicator of regime shifts. A manual ledger in
`research/06_capacity_ledger.md` is a v1 deliverable that
takes a few hours to populate.

**Add SEMI book-to-bill (#9.1)** as the second — one
URL, one scrape, one monthly value, with a 30-year
history. This is the cleanest free source for the
semiconductor-side demand signal.

**Defer the capacity-additions tracker (#8) to M2** — the
free alternatives are manual, the paid sources are
expensive, and the regime/ETA model is more sensitive to
the demand-side counter-signal (#9 + #10) than to
precise supply-side timing. We build the manual ledger
stub in v1 and automate in v2.

| Order | Source | Why this order |
|---|---|---|
| v1 stub | Hyperscaler capex (#10) | Highest signal, free, easy |
| v1 stub | SEMI book-to-bill (#9.1) | One URL, monthly scrape, decades of history |
| v1 stub | Capacity-additions ledger (#8 free alt) | Manual; defer automation to v2 |
| v2 | SEMI World Fab Forecast (#8 paid) | Needed for supply-side precision |
| v2 | Wood Mackenzie / UEA (#8 paid) | Needed for LPT precision |
