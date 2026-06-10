# Bottlewatch Value Chain Map

This document narrates the value chain DAG captured in
`00_value_chain.mmd` (canonical Mermaid source) and
`00_value_chain.json` (parsed DAG for the React Flow dashboard).
The map is a directed acyclic graph with **two parallel upstream tracks**
(silicon and power) that converge at the data center shell, then flow
downstream to inference at scale. Every node carries an explicit
**supplier-of-supplier** annotation — the extra step the user asked for —
so that any investor can drill upstream and see, e.g., that "advanced
packaging" is gated by ABF substrates from Ibiden / Shinko / Unimicron, or
that "transformers" needs grain-oriented electrical steel from
Cleveland-Cliffs.

## Prediction, not just location

The value chain map is not just a locator of bottlenecks — it is the
input to a **regime-prediction engine**. For every segment the scoring
system computes a level score `B(s, h)` (0-100) and a 6-month
backward-looking momentum `B'(s, h)` (-100 to +100), then labels the
segment with one of six computed regimes (PEAKING / PEAKED / RESOLVING /
EMERGING / STABLE / RESOLVING-from-low) and a directional resolution ETA
(<12mo / 12-24mo / >24mo). The DAG matters here because **announcements
travel along edges**: a power segment with high current tightness
(`B` = 90) is in a different regime from one with the same `B` but with
named capacity additions (GEV HA-class turbines, Three Mile Island
restart, Kairos / TerraPower SMR commissioning) ramping 12-18 months out,
because the second segment is in `PEAKED` and the first is still in
`PEAKING`. Likewise a silicon segment with high `B` and an HBM4 /
CoWoS-L ramp due in 6 months is `PEAKED`, while the same `B` with no
announced relief is `PEAKING`. The map's role is to make the edges and
supplier-of-supplier leaves legible enough that the regime call can
cite, e.g., "transformers are PEAKING but Cleveland-Cliffs GOES line 2
is commissioning 2026Q4, ETA 12-24mo" rather than a vibes-based
tightness judgment. The per-segment briefs in `01_segments/` close the
loop by enumerating the specific capacity additions, commissioning
dates, and demand-side relief that feed the regime computation.

## Bird's-eye shape

The graph has 16 main nodes split across four sectors:

- **MaterialsSector (2):** raw inputs, semiconductor materials.
- **HardwareSector (8):** front-end equipment, advanced-node fabs,
  advanced packaging, HBM memory, networking & interconnect,
  GPU/ASIC silicon, systems OEM/ODM, rack-scale integration.
- **InfrastructureSector (6):** fuel & power inputs, power generation OEM,
  transformers & switchgear, T&D utilities, data center shell, cooling &
  water.
- **DownstreamSector (1):** inference at scale.

The two tracks meet at `data_center_shell`, which has four inbound edges:

- `rack_scale_integration → data_center_shell` (silicon track; compute)
- `networking_interconnect → data_center_shell` (silicon track; fabric)
- `td_utilities → data_center_shell` (power track; electricity)
- `cooling_water → data_center_shell` (thermal; looped back from rack heat load)

A single outbound edge `data_center_shell → inference_at_scale` closes the
graph. The "loop" of heat from rack-scale back into cooling is the
single bi-directional-adjacent edge; modeling it as
`rack → cooling` keeps the graph a DAG while preserving the
load-following relationship.

## Why a DAG, not a Mermaid flow

The plan calls out that Mermaid SVG cannot support click-to-recenter
upstream navigation. The `.mmd` is the canonical artifact for the static
shareable view; `00_value_chain.json` is what `GET /v1/map` serves and
what React Flow renders. The JSON has the same node + edge information
plus a normalized `commodity` field on every edge so the SPARQL queries
that the ontology builder runs (see §10) can resolve transitive supply
chains in one hop.

## Per-node rationale

**raw_inputs (MaterialsSector).** Every physical layer of the AI stack
starts with molecules. Oil & gas feeds poly-silicon production and gas
turbine fuel. Mining produces copper (transformer windings, busbars),
rare earths (NdFeB magnets in wind turbine gearboxes and hard-disk
drives; dysprosium/terbium in high-temp applications), uranium
(enriched UF6 for SMRs and AP1000s) and lithium (UPS / battery backup
units on the data center floor). Water — both process ultra-pure water
for fabs and cooling-tower make-up — is the silent third leg; Taiwan's
worst drought in 2021 put TSMC's 3nm ramp at risk. Suppliers: XOM, CVX,
OXY, EOG, EQNR, Shell, BP (oil & gas); FCX, SCCO, MP, USA Rare Earth,
Albemarle (mining); CCJ, KAP, BWXT, Centrus (nuclear fuel cycle); AWK,
WMS, Veolia, Suez (water utilities).

**semiconductor_materials (MaterialsSector).** Photoresist (JSR, Shin-Etsu,
TOK, DuPont) is the single most concentrated input in the chain: EUV-grade
resist is essentially a JSR / Shin-Etsu duopoly. Silicon wafers
(Shin-Etsu, SUMCO, GlobalWafers) are also concentrated. Process gases
(Linde, Air Liquide, Air Products) — neon, helium, NF3, WF6, silanes —
sit on top of a Ukraine/Russia neon supply base that has been a
multi-year chokepoint. CMP slurries (CMC, Entegris, Fujimi) round out
the bill of materials.

**front_end_equipment (HardwareSector).** ASML is the only supplier of
EUV lithography systems — the single most concentrated node in the
entire AI supply chain. AMAT, LRCX, KLAC and Tokyo Electron round out
the deposition / etch / metrology stack. ASML's High-NA EUV (EXE:5000
and EXE:5200) is in customer hands at Intel (Oregon), Samsung and TSMC;
5-10 systems/year is the near-term volume. Sub-suppliers: Carl Zeiss
(optical lenses, also a single-source chokepoint), Gigaphoton
(EUV light sources, ASML JV with TRUMPF), Kawasaki HI / Yaskawa (vacuum
robotics), Edwards / Atlas Copco (vacuum pumps).

**advanced_node_fabs (HardwareSector).** TSMC commanded ~71% of the
global wafer foundry market in Q3 2025 (excluding Samsung) and ~67-68%
including Samsung. Samsung Foundry is a real second source but
struggles on leading-edge yield. Intel Foundry is a strategic third
leg, ramping 18A in Arizona. SMIC remains constrained by US export
controls at 7nm and below. Advanced node capacity is essentially a
TSMC + Samsung duopoly with Intel as a strategic entrant. Sub-suppliers:
municipal water + power utilities (TSMC's Hsinchu fabs alone consume
~9% of Taiwan's industrial water), Dow / DuPont / BASF / Mitsui (process
chemicals).

**advanced_packaging (HardwareSector).** This is the single most
binding near-term bottleneck in 2025-2026. TSMC's CoWoS capacity was
~37-40k wafers/month in 2024 and is targeted at ~65-75k by year-end
2025 and ~90k+ in 2026; demand still outstrips supply. NVIDIA takes
~60% of CoWoS allocation. Sub-suppliers: Ibiden, Shinko, Unimicron,
AT&S (ABF substrates — a known chokepoint in 2.5D advanced packaging);
Tanaka, MKE (UBM / bonding wire).

**hbm_memory (HardwareSector).** SK hynix is the clear HBM leader with
~57-64% market share in 2025, ramping HBM4 in 2026 for NVIDIA Rubin;
UBS projects hynix at ~70% of NVIDIA HBM4 supply. Samsung is at
~25-35% (delayed by HBM3E qualification issues). Micron holds
~10-20% with HBM3E in volume for NVIDIA Blackwell. Total HBM market
~$54.6B in 2026 (BofA). Sub-suppliers: shared DRAM process platform
(Samsung / hynix / Micron 1y/1z/1c nodes); ASMPT, Kulicke & Soffa, Hanmi
(TSV bonding equipment).

**networking_interconnect (HardwareSector).** Two non-overlapping
sub-markets: scale-up (NVLink, NVSwitch, UALink) and scale-out
(Spectrum-X Ethernet, Arista 7800R4, Cisco Silicon One G200, UEC 1.0).
Broadcom (AVGO) and Marvell (MRVL) supply most switch silicon to the
non-NVIDIA fabric ecosystem. Optical transceivers (800G/1.6T) are a
real chokepoint: Coherent, Lumentum, Innolight, Eoptolink are the
suppliers; NVIDIA's Spectrum-X Photonics with co-packaged optics
(announced GTC March 2025, production 2026) integrates optical
components directly with TSMC switches. Sub-suppliers: high-speed PCB
(Unimicron, Ibiden, Shinko, AT&S); switch ASICs (Broadcom, Marvell,
Cisco Silicon One).

**gpu_asic_silicon (HardwareSector).** NVIDIA dominates accelerator
silicon (~90%+ of training-class AI accelerator revenue at
top hyperscalers in 2025), with AMD Instinct MI400/MI450 ramping.
Hyperscaler ASIC programs (Google TPU v7p/v7e, AWS Trainium 3, Microsoft
Maia) collectively account for meaningful but secondary share.
Sub-suppliers: Monolithic Power, Renesas, TI, Onsemi (on-die / on-board
power delivery — a chokepoint as 800V rack architectures emerge);
Arm, Synopsys, Cadence, SiFive (IP cores / EDA tools).

**systems_oem_odm (HardwareSector).** For GB200/GB300 rack-scale,
Foxconn (Hon Hai) is the leading ODM with ~40-50% of NVIDIA's rack
integration orders, Quanta is the other major ODM partner, and
Wiwynn (Wistron subsidiary) is the third leg. For more traditional
hyperscale server builds, SMCI, Dell (DELL), HPE and the ODM trio
above all participate. Sub-suppliers: Delta, Lite-On, FSP, Advanced
Energy (PSUs — Advanced Energy / Onsemi announced a 12kW SiC-based
PSU for AI servers in 2025); Foxconn, Wiwynn, Inventec, Quanta
(chassis, with overlap into the ODM role itself).

**rack_scale_integration (HardwareSector).** This node represents the
move from per-server SKUs to full rack products: NVL72 (Blackwell),
MGX, and the rack-level thermal / power / fabric integration that
NVIDIA's HGX/DGX systems pioneered. NVIDIA itself is the dominant
player; Schneider Electric and Vertiv are the key infra partners;
GRC (LiquidCool), Boyd, CoolIT, Asetek supply CDUs; Eaton, ABB, Vertiv
supply busbars and power shelves. Sub-suppliers: CoolIT, Vertiv, Boyd,
Asetek, Schneider (CDUs); Eaton, Schneider, ABB, Vertiv (busbars /
power shelves).

**fuel_power_inputs (InfrastructureSector).** The feedstock that flows
into the power generation OEM node. Includes upstream oil & gas (XOM,
CVX, OXY, EOG), uranium (CCJ, KAP, Cameco), mining (FCX, SCCO, MP,
Albemarle, Pilbara), and renewable developers (NEE, ENPH, BEP). The
"renewable developer" entry is included because PPAs from NEE, AEP
and others are increasingly bundled into data center site selection;
the canonical fuel commodity is gas/uranium/minerals.

**power_generation_oem (InfrastructureSector).** Gas turbines (GEV,
Siemens Energy, Mitsubishi HI) are the dominant near-term capacity
additions for AI data center campuses; GE Vernova's backlog grew
substantially through 2024-2025 on the strength of gas turbine
orders. SMR and AP1000 nuclear (Westinghouse, BWXT, Holtec, NuScale,
X-energy) are the long-duration play. Wind and solar (Vestas, GEV,
First Solar, Jinko, Enphase) are intermittent. Sub-suppliers: rare
earths (MP, USA Rare Earth, Lynas) for wind turbine magnets; SMR
developers as the nuclear sub-segment.

**transformers_switchgear (InfrastructureSector).** This is the
binding near-term constraint on data center electrification in the
US. Large power transformer (LPT) lead times were reported at
**128 weeks (over 2 years)** in 2025 by trade press, up from 12-18
months pre-pandemic — some specialty quotes have reached 200 weeks.
Grain-oriented electrical steel (GOES) supply is the upstream
chokepoint, dominated by Cleveland-Cliffs in the US and Posco in
Korea. Copper (FCX, SCCO) is the second upstream chokepoint.
Players: GEV, HUBB, Eaton, Schneider, Hitachi, Siemens Energy, ABB,
Mitsubishi Electric, Toshiba.

**td_utilities (InfrastructureSector).** Investor-owned utilities
(NEE, SO, DUK, AEP, Dominion, Exelon, Constellation, Vistra, Xcel) and
international utilities (Iberdrola, Enel, Engie, RWE) own the
transmission and distribution infrastructure. They are the gatekeepers
for new data center interconnections, and FERC interconnection queue
delays in PJM, MISO and ERCOT are now multi-year. Sub-suppliers:
FERC, state PUCs, ISO/RTOs (PJM, ERCOT, CAISO, MISO, NYISO, ISO-NE,
SPP) — the regulators that bottleneck new capacity additions.

**data_center_shell (InfrastructureSector).** Colocation REITs (EQIX,
DLR) plus hyperscalers (MSFT, GOOG, AMZN, META) operating their own
self-build. EQIX's Q3 2025 backlog grew to $5.7B with 33% from
AI-related customers; DLR's Q3 2025 backlog reached $7.2B with
$1.4B in new leases signed in a single quarter, a 75% YoY increase
in total leasing. This is the convergence node. Sub-suppliers:
colo REITs (EQIX, DLR, AMT, IRM, CCI) as the supply base itself;
land/tower REITs (AMT, CCI) for site control; dark fiber (Lumen,
Zayo, Crown Castle, Equinix Fabric) for connectivity.

**cooling_water (InfrastructureSector).** Air cooling breaks down past
~40 kW per rack; modern AI pods run 60-120 kW, with NVIDIA's GB200
NVL72 and the announced Rubin platform pushing higher. The
liquid-cooling market grew from ~$3.6B in 2024 to a projected $15B
by 2029 (CAGR ~30%). Vertiv's Q3 2025 backlog hit $9.7B
([fierce-network.com](https://www.fierce-network.com/cloud/ai-demand-drove-q3-2025-vertiv-earnings-backlog-hits-9-7b)),
Schneider Electric's data center liquid cooling business is
scaling similarly. Sub-suppliers: chillers (Trane, Carrier, JCI),
pumps (Flowserve, Xylem, Mueller, Roper), water treatment chemicals
(Ecolab, Solenis, Veolia, Pentair).

**inference_at_scale (DownstreamSector).** The single demand node.
Hyperscalers (MSFT, GOOG, AMZN, META, ORCL) absorb most of the AI
compute. Neoclouds (CRDO, NBIS, plus private CoreWeave, Lambda)
represent the third-tier of demand and are growing fast.
Combined 2026 hyperscaler capex is projected at ~$400B, up from
~$300B in 2025. Sub-suppliers: neoclouds (CRDO, NBIS, PLTR, CoreWeave,
Lambda) and enterprise SaaS (M365, Workspace, Adobe, Salesforce) as
the user-facing consumption layer.

## Why convergence at the data center

The two-track DAG is not symmetric. The silicon track is a
~5-deep pipeline (raw → materials → equipment → fabs → packaging/HBM
→ silicon → systems → rack) with tight capacity coupling at fabs and
packaging. The power track is a ~4-deep pipeline (fuel → generation →
transformers → utilities) with even tighter capacity coupling at
transformers. Both terminate at the data center shell because
**compute capacity is the product of both** — you cannot run a GB200
without both the silicon and the megawatt. The shell is the natural
multiplication point for the bottleneck score.

## Edge semantics

- `supplies` — role-to-role edges. `advanced_packaging` `supplies`
  `gpu_asic_silicon` is a role-to-role production relationship.
- `suppliesCommodity` — leaf-to-parent edges. `mat_silicon_wafers`
  `suppliesCommodity` `semiconductor_materials` for `silicon_wafer`.
- `dependsOnCommodity` — parent-to-leaf edges recording what the
  parent role depends on. `gpu_asic_silicon` `dependsOnCommodity`
  `hbm_stack` from `hbm_memory`.

This three-way split is what the §10 ontology uses: `supplies`,
`suppliesCommodity` and `dependsOnCommodity` are object properties on
`:Role` and `:Commodity`. The JSON's `commodity` field is null for
`supplies` edges and populated for the other two.

## Stats

- 16 main nodes
- 41 supplier-of-supplier leaves
- 57 total nodes
- 59 edges
- 4 sectors represented
- 58 unique commodity types (see `commodities` array in JSON)

## Open questions

- HBM4 capacity allocation: estimates vary 50-70% for SK hynix's 2026
  share of NVIDIA's Rubin platform; pending NVIDIA's Rubin launch
  confirmation.
- LPT lead times: trade press has reported both 128 weeks and 200 weeks
  depending on manufacturer; the official 200-week figure (sometimes
  cited for Hitachi Energy and certain specialty units) needs
  primary-source confirmation.
- The `rack → cooling` edge is a heat-load feedback loop; modeled
  directionally to keep the DAG acyclic, but a future revision could
  expose this as a bi-directional relationship via edge annotation.
