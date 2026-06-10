# Cooling & Water

## 1. Definition & boundary (NAICS)

- **NAICS 333415** (Air-Conditioning and Warm Air Heating
  Equipment and Commercial and Industrial Refrigeration
  Equipment Manufacturing) for chillers and CRAC/CRAH.
  **NAICS 333911** (Pumps and Pumping Equipment
  Manufacturing) for pumps. **NAICS 3251** (Basic Chemical
  Manufacturing) for water treatment chemicals.
- Covers **chillers** (air-cooled, water-cooled, adiabatic,
  evaporative), **CDUs and direct-to-chip cold plates**,
  **immersion cooling fluids and tanks**, **pumps and
  valves**, **cooling towers and dry coolers**, **water
  treatment chemicals** (scale, corrosion, biological
  control), and **water utilities / make-up water
  supply** for hyperscale data centers.
- Excludes the rack-scale CDU / busbar / power shelf
  (covered in `rack-scale-integration.md`); the chiller
  + cooling-tower side is the building-level thermal
  rejection system.

## 2. Demand drivers (with units)

- **Liquid cooling market** — ~$3.6B in 2024, projected
  ~$15B by 2029 (CAGR ~30%, multiple analyst estimates).
- **Rack power density** — 40 kW/rack breaks air cooling;
  GB200 NVL72 is 60-80 kW/rack; Rubin-era targets 100-130
  kW+/rack. Above 50 kW, all-architecture is liquid.
- **Hyperscaler data center water consumption** —
  100 MW data center with conventional cooling uses
  ~360,000 gallons/day (~130M gallons/year); hyperscale
  sites use 1-2M gallons/day. Data center water
  consumption projected to more than double by 2030,
  reaching 75-200B gallons/year.
- **Sustainability mandate** — hyperscaler PUE targets
  (1.1-1.2 for new builds) and WUE (water usage
  effectiveness) targets are driving investment in
  closed-loop liquid and immersion cooling, which can
  reduce water consumption by up to 90% vs. traditional
  evaporative cooling.
- **Immersion cooling** — Microsoft has publicly
  committed to two-phase immersion at scale; sub-suppliers
  include Shell (S5/Immersion Fluid), 3M (Novec —
  though 3M exited PFAS production by 2025), F-Gas
  alternatives (Chemours, Honeywell).

## 3. Supply side: capacity, lead times, utilization

- **Trane Technologies (TT)** — chillers, heat pumps,
  thermal management; strong data center exposure
  via the Trane / Thermo King brands.
- **Carrier Global (CARR)** — chillers, data center
  cooling (Carrier AquaEdge, Evergreen, etc.); split
  from United Technologies 2020.
- **Johnson Controls (JCI)** — YORK chillers, building
  automation, data center cooling.
- **Vertiv (VRT)** — CDU, Liebert in-row and in-room
  cooling; Q3 2025 backlog $9.7B; AI is dominant
  driver.
- **Schneider Electric (SU.PA)** — EcoStruxure data
  center cooling, CDU.
- **Flowserve (FLS)** — pumps, valves, seals.
- **Xylem (XYL)** — pumps, water treatment; Pure
  Technologies (smart water monitoring).
- **Mueller Water Products (MWA)** — water
  infrastructure; chillers and pumps adjacent.
- **Ecolab (ECL)** — water treatment chemicals;
  ~$15B revenue, growing AI data center exposure.
- **Solenis (private, Platinum Equity)** — water
  treatment chemicals; ~$2.5B revenue.
- **Veolia (VIE.PA)** — water and wastewater services;
  hyperscaler partnership with AWS, Microsoft, Google.
- **Pentair (PNR)** — water filtration and treatment.
- **Boyd (private), CoolIT (private), Asetek
  (ASETEK.OL)** — CDU / DTC cooling.
- **Lead time** — chillers 50-80 weeks for large
  data center units; CDU 3-6 months.

## 4. Chokepoints

- **Water availability at siting** — Phoenix, Abilene,
  Las Vegas are all in water-stressed regions; siting
  new 1 GW data centers in these regions requires
  closed-loop or air-cooled designs, which raises
  capex and reduces PUE.
- **Refrigerant regulations** — F-Gas Regulation (EU)
  and the American Innovation and Manufacturing (AIM)
  Act phase out high-GWP refrigerants (R-134a, R-410A)
  by 2030-2036; transition to low-GWP alternatives
  (R-1234ze, R-454B, CO2) is a multi-year
  qualification cycle.
- **Chilled water capacity** — a 100 MW data center
  can require 50,000-100,000 tons of chilled water
  capacity; chillers are 500-1,500 tons each, so
  dozens of units.
- **Pump / flow control** — at 100+ kW/rack, the
  volumetric flow and pressure requirements on
  CDUs are non-trivial; pump + valve selection is
  an engineering challenge.
- **Immersion fluid supply** — 3M exited PFAS
  production by 2025; Shell and Chemours are the
  scaling alternatives.

## 5. Public players

- **WTS** (Watts Water Technologies, US) — water
  systems, valves, flow control; smaller-cap
  exposure.
- **TT** (Trane Technologies, US/Ireland) —
  chillers, data center cooling; ~30-40% data
  center exposure.
- **CARR** (Carrier Global, US) — chillers, data
  center cooling; ~20-30% data center exposure.
- **JCI** (Johnson Controls, US/Ireland) — YORK
  chillers, BMS; ~20-30% data center exposure.
- **VRT** (Vertiv, US) — CDU, in-room cooling;
  ~80% data center exposure.
- **Schneider Electric (SU.PA)** — CDU, building
  cooling, EcoStruxure.
- **FLS** (Flowserve, US) — pumps, valves, seals;
  ~10-20% data center exposure.
- **XYL** (Xylem, US) — pumps, water treatment.
- **MWA** (Mueller Water Products, US) — water
  infrastructure.
- **ECL** (Ecolab, US) — water treatment chemicals;
  ~5-10% data center exposure but growing.
- **PNR** (Pentair, US) — water filtration and
  treatment.
- **Veolia (VIE.PA)** — water utility + services;
  France-listed.
- **Suez (private)** — water utility + services;
  acquired by Veolia-merger consortium.
- **AWK** (American Water Works, US) — US
  water utility.
- **WMS** (Watts Water — see WTS above for
  ticker); **WTS** is the relevant public ticker
  for water systems.

## 6. Lead indicators (track daily/weekly)

- **Vertiv backlog** — quarterly, the cleanest
  read on liquid cooling.
- **Trane / Carrier / Johnson Controls commercial
  HVAC revenue** — quarterly; data center is a
  sub-segment.
- **Ecolab industrial / water segment growth** —
  quarterly.
- **Liquid cooling pricing** — channel checks on
  CDU ASP.
- **Drought / water stress** — US Drought Monitor
  weekly; EPA WaterSense data; state water
  authority restrictions.
- **USGS water use data** — annual, lagged; a
  confirmatory indicator.

## 7. Open questions / data gaps

- **Liquid-to-liquid (L2L) vs. liquid-to-air (L2A)
  market split** — L2L is the trend for >2 MW pods
  but adoption rates are not publicly disclosed.
- **Immersion cooling adoption** — Microsoft
  committed to two-phase immersion at scale;
  other hyperscalers' adoption rates are
  not disclosed.
- **Refrigerant transition pace** — EU F-Gas
  timeline vs. US AIM Act; substitution options
  (R-1234ze, R-454B, CO2) all have different
  performance tradeoffs.
- **Closed-loop water reuse ROI** — water
  reuse systems capex is $20-50M for a 100 MW
  site; payback depends on water cost and
  regulation, which varies dramatically by
  jurisdiction.
- **Water utility involvement** — AWK, Veolia,
  and Suez are increasingly the
  infrastructure counterparties to data
  center siting; the financial structure of
  these deals (PPA-like, build-operate, raw
  water service) is a 2026-2027 emerging theme.

## 8. Momentum & direction

Direction over the last 6 months: **plateauing at the
chiller / CDU / water-treatment layer, EMERGING at the
immersion-cooling layer**. The segment is downstream of
the rack-scale and data-center-shell segments, so its
regime is a function of the buildout cadence plus a
sustainability overlay.

Leading indicators pointing toward plateauing at the
chiller / CDU layer:

- **Trane / Carrier / Johnson Controls commercial
  HVAC revenue** has been growing but the growth rate
  has decelerated; Q1 2026 commentary shifted from
  "AI-driven demand" to "more mixed order book."
- **Ecolab industrial / water segment growth** is
  still positive but at low single digits, not the
  high single digits of 2024-2025.
- **Chiller lead times** have stabilized at 50-80
  weeks for large data center units, down from a
  reported peak of 100+ weeks in mid-2024.

Leading indicators still pointing toward tightening
in specific sub-layers:

- **Liquid-to-liquid (L2L) CDUs** at hyperscale are
  scaling but supply is still tight; Vertiv / Boyd /
  Schneider are the named suppliers.
- **Water treatment chemicals** at hyperscale sites
  (Ecolab, Solenis, Veolia) are growing at 8-12%
  YoY — a slower growth than 2024 but still above
  GDP.

Leading indicators pointing toward EMERGING at the
immersion-cooling layer:

- **Microsoft** has publicly committed to two-phase
  immersion at scale; the
  sub-suppliers (Shell S5/Immersion Fluid, 3M Novec
  exiting PFAS by 2025, Chemours / Honeywell F-Gas
  alternatives) are scaling.
- **Submersion / immersion tank** suppliers (GRC,
  Asperitas, etc.) are pre-IPO / private; segment
  is too small to be a 2026-2027 capex event but is
  a 2027+ watch-item.

`B'` reading (subjective, 6mo backward look): **roughly
0 to -5** at the segment level. The plateau at the
chiller / CDU layer is the dominant signal.

## 9. Resolution timeline

The binding relief valves:

- **Trane / Carrier / Johnson Controls chiller
  capacity** — being expanded; first waves of new
  capacity H2 2026, full effect 2027.
- **Vertiv / Boyd / CoolIT / Asetek CDU capacity**
  — being expanded; H2 2026 full effect.
- **Ecolab / Solenis / Veolia water-treatment
  capacity** — scaling with the buildout, no
  binding constraint.
- **Immersion fluid supply** — Shell S5/Immersion
  Fluid is scaling; 3M Novec exit is being offset
  by Chemours / Honeywell alternatives.

Demand-side relief:

- **PUE / WUE efficiency mandates** drive investment
  in closed-loop liquid and immersion cooling, but
  do not reduce absolute demand; they shift mix
  toward higher-value systems.
- **Water-availability siting constraints** (Phoenix,
  Abilene, Las Vegas) are driving capacity toward
  closed-loop designs, which increases the chiller /
  CDU intensity per MW.

ETA bucket: **<12 months** for the chiller / CDU
layer to reach STABLE; **12-24 months** for the
immersion layer to become a meaningful sub-segment.

## 10. Regime call

**Regime: STABLE** at the chiller / CDU / water
treatment layer; **EMERGING** at the immersion
cooling layer. Net segment regime: **STABLE** with
EMERGING sub-trend.

Confidence: **Medium-High**. The chiller / CDU
layer is a clear STABLE call (lead times shortening,
growth rate decelerating, capacity being added).
The immersion sub-layer is EMERGING but too small
to flip the segment-level call.

This segment is **NOT** in RESOLVING, so it remains
fully eligible for the long basket.

Watch-items that would flip the regime: (a) a major
US drought / water-restriction order that
re-constrains water-availability siting (could push
to PEAKING), (b) hyperscaler immersion adoption
acceleration (would push to PEAKING), (c) Trane /
Carrier / Johnson Controls capacity constraint
emergence.
