# Data Center Shell (Colo + Hyperscaler Self-Build)

## 1. Definition & boundary (NAICS)

- **NAICS 531120** (Lessors of Nonresidential Buildings) for
  shell / wholesale data center REITs; **NAICS 5182** (Data
  Processing, Hosting, and Related Services) for the
  hyperscaler self-build asset class.
- Covers **colocation REITs** (EQIX, DLR, AMT, IRM, CCI),
  **wholesale / build-to-suit** operators (Stack, QTS, CyrusOne
  via KKR, Vantage, Aligned, EdgeConneX), and **hyperscaler
  self-build** capacity (MSFT, GOOG, AMZN, META, ORCL, Apple,
  Meta, CoreWeave).
- Excludes power generation (covered in `power-generation-oem.md`)
  and cooling (covered in `cooling-water.md`).

## 2. Demand drivers (with units)

- **Hyperscaler AI capex** — combined 2026 ~$400B vs ~$300B
  in 2025; ~10-15% flows into shell / land / build.
- **Pre-lease activity** — EQIX Q3 2025 backlog $5.7B,
  +20% YoY; 33% of Q3 2025 bookings ($377M total) from
  AI-related customers. Source:
  [Equinix Q3 2025](https://investor.equinix.com/newsroom/news-details/2025/Equinix-Reports-Third-Quarter-2025-Results-1413/default.aspx).
- **DLR Q3 2025 new leases** — $1.4B signed in the quarter;
  total backlog $7.2B; +75% YoY in total leasing. Source:
  [DLR Q3 2025](https://www.digitalrealty.com/about/newsroom/press-releases/digital-realty-reports-third-quarter-2025-results).
- **Power availability** — the binding constraint on new
  shell buildout; PJM, ERCOT, CAISO all multi-year queue.

## 3. Supply side: capacity, lead times, utilization

- **Equinix (EQIX)** — retail colocation + xScale
  hyperscale BTS; 30 large new logo wins in Q3 2025;
  $5.7B backlog.
- **Digital Realty (DLR)** — wholesale + hyperscale BTS;
  $7.2B backlog; $1.4B new leases Q3 2025.
- **American Tower (AMT)** — towers + data center
  (CoreSite acquisition); less of a pure-play.
- **Iron Mountain (IRM)** — colocation (data center in
  converted storage facilities).
- **Crown Castle (CCI)** — towers + fiber; small DC
  exposure.
- **Hyperscaler self-build** — MSFT, GOOG, AMZN, META, ORCL
  collectively own and operate the majority of new AI
  data center capacity built in 2024-2025.
- **CoreWeave (CRWD-not-public, then CRDO-listed for
  related)** — neocloud with own DC footprint.
- **Equinix Fabric, Lumen (LUMN), Zayo, Crown Castle** —
  dark fiber / interconnection suppliers.

## 4. Chokepoints

- **Power availability** — primary chokepoint. PJM
  interconnection queue >2 years; ERCOT, CAISO similarly
  constrained. Hyperscalers increasingly sign PPAs directly
  with generation owners (Talen-Amazon, Microsoft-Constellation,
  Google-Kairos SMR).
- **Land / zoning** — Northern Virginia (Loudoun, Prince
  William counties), Phoenix, Dallas, Atlanta are the
  primary US clusters; new zoning in Texas (Abilene for
  Stargate), Wyoming, Indiana (for SMRs).
- **Transformer delivery** — see `transformers-tnd.md`;
  LPT 128+ week lead times directly delay shell
  commissioning.
- **Water** — cooling-tower make-up water in arid
  locations (Phoenix, Abilene) is a 2025-2026
  siting constraint.
- **Sustainability / community opposition** — Loudoun
  County has begun tightening data center zoning;
  local opposition is growing in multiple jurisdictions.

## 5. Public players

- **EQIX** (Equinix, US) — pure-play colo + interconnection;
  $5.7B backlog; ~95% data center exposure.
- **DLR** (Digital Realty, US) — pure-play wholesale +
  hyperscale BTS; $7.2B backlog.
- **AMT** (American Tower, US) — towers primary, data
  center secondary.
- **IRM** (Iron Mountain, US) — records storage + colocation.
- **CCI** (Crown Castle, US) — towers + fiber + small
  data center.
- **MSFT** (Microsoft, US) — hyperscaler self-build, the
  largest single owner-operator of AI capacity.
- **GOOG** (Alphabet, US) — hyperscaler self-build.
- **AMZN** (Amazon, US) — hyperscaler self-build (AWS).
- **META** (Meta Platforms, US) — self-build for AI
  training and inference.
- **ORCL** (Oracle, US) — hyperscale; the OCI / sovereign
  AI play.
- **CRDO** (CoreWeave, US) — neocloud with own DC
  footprint; leveraged to AI demand.

## 6. Lead indicators (track daily/weekly)

- **EQIX quarterly bookings + backlog** — the cleanest
  retail colocation indicator.
- **DLR quarterly leasing + backlog** — the cleanest
  wholesale / hyperscale indicator.
- **Hyperscaler capex guidance** — quarterly.
- **PJM / ERCOT / CAISO interconnection queue length**
  — published monthly/quarterly; the upstream power
  constraint.
- **Talen-Amazon, Microsoft-Constellation, Google-Kairos
  PPA announcements** — proxy for AI-driven generation
  development.
- **Wells Fargo Data Center REIT quarterly update** —
  published quarterly, covers EQIX, DLR, AMT, IRM.

## 7. Open questions / data gaps

- **AI-driven MW pipeline by region** — total contracted
  but unbuilt AI capacity in 2027-2028 is hard to source
  directly; analyst estimates put it at 50-100 GW
  globally.
- **Hyperscaler self-build vs. colo split** — trend
  favors self-build, but colo pre-lease growth is also
  strong; the structural mix is not yet settled.
- **The 800V HVDC transition in shell design** — new
  data centers are being designed around 800V HVDC
  distribution; this favors Vertiv, Eaton, ABB but
  requires material shell redesign (electrical room
  sizing, transformer spec, busbar layout).
- **Sovereign AI site selection** — Saudi (Humain),
  UAE (G42), India, Japan, Korea, EU all announcing
  multi-GW sites; financial close timing is the
  load-bearing variable.

## 8. Momentum & direction

Direction over the last 6 months: **PEAKING, with the
2026 power-availability constraint becoming the binding
choke point**. The data center shell is the convergence
node for both tracks, so its regime is a product of
the silicon track (rack-scale, networking) and the
power track (generation, transformers, utilities).

Leading indicators pointing toward PEAKING:

- **EQIX Q3 2025 backlog** $5.7B with 33% from AI
  customers; Q1 2026 commentary suggested backlog
  growth decelerating from the 2024-2025 surge.
- **DLR Q3 2025 backlog** $7.2B with $1.4B in new
  leases; Q1 2026 new-lease run-rate has slowed to
  ~$1.0-1.2B / quarter.
- **Hyperscaler capex** 2026 ~$400B is up ~30% YoY
  from 2025; the shell-layer revenue capture is
  roughly proportional but the *rate* of new-lease
  signing is decelerating.

Leading indicators still pointing toward tightness:

- **Power availability** remains the binding
  constraint. PJM, ERCOT, CAISO interconnection
  queue is multi-year; new data center sites are
  increasingly constrained by upstream power.
- **Transformer delivery** at 128+ week LPT lead
  times is directly delaying shell commissioning
  (see `transformers-tnd.md`).
- **Land / zoning** in Loudoun County, Northern
  Virginia, and other primary clusters is becoming
  a 2026-2027 binding constraint.

`B'` reading (subjective, 6mo backward look): **roughly
+5 to +15** at the segment level. The segment is
still tightening, with the rate of new-lease
signing decelerating but absolute MW pipeline still
growing.

## 9. Resolution timeline

The binding relief valves:

- **Hyperscaler self-build** (MSFT, GOOG, AMZN, META,
  ORCL) — the dominant new capacity vector; self-build
  capex is the supply side, not a relief.
- **PPA-driven behind-the-meter generation** (Talen
  -Amazon, Microsoft-Constellation, Google-Kairos,
  Meta-Soltage) — these are 2026-2027 supply events
  that add power to the grid, but are gated by
  generation OEM + transformer + utility timelines.
- **New colo development** (Stack, QTS / Blackstone,
  CyrusOne / KKR / GIP, Vantage, Aligned, EdgeConneX)
  — multi-year build pipelines; first deliveries
  2026-2027.
- **Three Mile Island restart** (Microsoft
  -Constellation) — 2028 targeted; structural relief
  for the 2028+ outlook.
- **SMR / AP1000 commissioning** (TerraPower Natrium
  2030, Kairos / TVA 2030, X-energy Dow 2030+) —
  2030+ supply events; not a 2026-2028 relief.

Demand-side relief:

- **Hyperscaler capex moderation** — none yet in
  2026. Watch 2027 guidance.
- **Sovereign AI capex** — adds demand, not relief.
- **Sustainability / community opposition** —
  Loudoun County has begun tightening data center
  zoning; this could moderate new-site growth in
  specific jurisdictions but is a 2026-2027 watch
  item.

ETA bucket: **>24 months** for full resolution. The
combination of (a) multi-year power interconnection
queue, (b) 128+ week transformer lead times, (c)
siting / zoning friction, and (d) hyperscaler capex
still at peak makes the shell a 2027-2028 relief
story, not a 2026 one.

## 10. Regime call

**Regime: PEAKING** (segment tightness still in the
upper range; the rate of new-lease signing is
decelerating but absolute MW pipeline still growing).

Confidence: **Medium-High**. The shell is structurally
a PEAKING segment because it inherits PEAKING from
both upstream tracks (CoWoS + HBM on the silicon
side, transformers + power on the infrastructure
side). The only way the shell resolves faster than
its upstreams is if hyperscaler capex moderates
sharply, which is not yet signaled.

This segment is **NOT** in RESOLVING, so it remains
fully eligible for the long basket. For the short
basket, B × |B'| is high.

Watch-items that would flip the regime: (a) a
major hyperscaler capex guidance cut for 2027,
(b) successful PJM / ERCOT interconnection queue
reform (FERC Order 2023), (c) Three Mile Island
restart acceleration, (d) any large-scale
behind-the-meter PPA financial close.
