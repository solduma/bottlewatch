# Networking & Interconnect

## 1. Definition & boundary (NAICS)

- **NAICS 3342** (Communications Equipment Manufacturing) for
  switches and optical, plus **NAICS 3344** for the underlying
  switch ASICs and PHYs.
- Covers **scale-up fabric** (NVLink, NVSwitch, UALink, Infinity
  Fabric) and **scale-out fabric** (Spectrum-X Ethernet, Arista
  Etherlink, Cisco Nexus, Broadcom Tomahawk / Jericho, Marvell
  Alaska / Inphi). Includes **optical transceivers** (800G, 1.6T
  DR8/FR4, LPO, CPO) and **high-speed PCB / substrate** as a
  binding sub-input.
- Excludes traditional enterprise switching, WiFi, and 5G RAN.

## 2. Demand drivers (with units)

- **AI cluster size** — Frontier training clusters are 50k-1M+
  GPU; an NVL72 pod is 72 GPUs interconnected via NVLink Switch,
  requiring ~9 NVSwitches per pod, scaling to ~9,000+ NVSwitches
  for a 100k-GPU cluster.
- **Ethernet fabric build** — UEC 1.0 spec released June 11,
  2025. Arista, Cisco, Broadcom, Marvell all building 51.2-460
  Tbps switch generations. The Ultra Ethernet Consortium
  includes AMD, Intel, Microsoft, OpenAI as steering members.
- **Co-packaged optics** — NVIDIA Spectrum-X Photonics
  (announced GTC 2025, production 2026) integrates optical
  directly with the switch ASIC at 1.6 Tbps/port. Coherent
  (COHR), Lumentum (LITE), Corning (GLW), SENKO, Foxconn are
  the named partners.
- **Cabling / optical transceiver TAM** — 800G in 2025; 1.6T
  inflection in 2026; total AI optical TAM projected $20-30B
  by 2027 (LightCounting / Dell'Oro estimates).

## 3. Supply side: capacity, lead times, utilization

- **Broadcom (AVGO)** — Tomahawk 5 (51.2 Tbps) and Jericho3-AI
  (460 Tbps) feed most non-NVIDIA scale-out switch platforms.
  Custom AI ASIC (Google TPU partner, Meta MTIA partner).
  Backlog at record levels through 2026.
- **Arista Networks (ANET)** — Etherlink 7060X6 + 7800R4 AI
  platforms; UEC-aligned; 30k+ accelerator fabric support.
- **Marvell (MRVL)** — Alaska / Inphi DSP and PAM4 optical
  platforms; custom ASIC (AWS Trainium partner).
- **Cisco (CSCO)** — Silicon One G200, Nexus 9300/9400 series;
  UEC steering member.
- **NVIDIA networking** — Quantum-X800 (InfiniBand),
  Spectrum-X (Ethernet), NVLink Switch, BlueField SuperNIC;
  ConnectX-8 and BlueField-4 in 2026.
- **Optical: Coherent (COHR), Lumentum (LITE), Innolight,
  Eoptolink** — 800G / 1.6T transceivers. Innolight is the
  largest independent optical transceiver supplier to NVIDIA
  in 2024-2025.
- **Lead times** — Optical transceivers have been 4-6 months
  at peak; new 1.6T products are by-allocation. Switch
  systems are also allocated.

## 4. Chokepoints

- **Optical transceiver supply** — Innolight, Coherent,
  Lumentum, Eoptolink are the four major 800G suppliers.
  1.6T qualification is underway at all four but yield is
  the gating factor.
- **High-speed PCB / substrate** — 100+ layer boards for
  800G/1.6T switches are limited to a small number of
  suppliers (Unimicron, Ibiden, Shinko, AT&S).
- **Switch ASIC capacity** — Broadcom Tomahawk 5, Marvell
  Inphi, Cisco Silicon One G200 are the three scale-out
  platforms; capacity is constrained at TSMC's N5/N3 nodes
  shared with hyperscaler customers.
- **DSP / SerDes** — Marvell (Inphi) Alaska PAM4 DSP is
  the industry default; 200 Gbps/lane SerDes is the
  2026-2027 frontier.
- **Standards fragmentation risk** — NVIDIA Spectrum-X
  vs. UEC 1.0 vs. Broadcom SUE (Scale-Up Ethernet). The
  Ethernet-fabric standard for AI is not yet unified; this
  creates incremental demand for each platform.

## 5. Public players

- **NVDA** (NVIDIA) — networking is ~15-20% of total
  revenue; ConnectX / BlueField / Spectrum-X / NVSwitch
  portfolio.
- **AVGO** (Broadcom) — AI revenue (custom ASIC + Tomahawk
  switch ASIC) at $20B+ run-rate; ~70% pure-play AI
  exposure.
- **ANET** (Arista Networks) — ~60-70% revenue from
  hyperscaler / cloud; AI is the growth vector.
- **CSCO** (Cisco) — smaller AI networking share but
  scaling with Silicon One G200.
- **MRVL** (Marvell) — AI revenue scaling; custom ASIC +
  Alaska / Inphi DSP.
- **COHR** (Coherent) — 800G / 1.6T transceivers; CPO
  partnership with NVIDIA.
- **LITE** (Lumentum) — laser components; CPO partnership
  with NVIDIA.
- **GLW** (Corning) — optical fiber and glass; CPO
  partnership with NVIDIA.
- **Innolight (300308.SZ)** — Chinese-listed optical
  transceiver leader, ~70%+ revenue from AI / cloud.
- **Eoptolink (300502.SZ)** — another Chinese-listed
  optical transceiver supplier.

## 6. Lead indicators (track daily/weekly)

- **Broadcom AI revenue run-rate** — disclosed quarterly
  in earnings commentary; the cleanest single indicator
  for non-NVIDIA AI silicon demand.
- **Arista 7800R4 AI platform revenue mix** — quarterly
  call commentary.
- **NVIDIA networking revenue** — disclosed within Data
  Center segment.
- **Optical transceiver ASP** — Innolight, Coherent,
  Lumentum pricing; sell-side channel checks.
- **UEC compliance certifications** — Ultra Ethernet
  Consortium certification announcements.
- **CPO production announcements** — NVIDIA Spectrum-X
  Photonics, Coherent CPO, Broadcom CPO.

## 7. Open questions / data gaps

- **1.6T transceiver yield** — pending verification
  across the four major suppliers.
- **UEC vs. Spectrum-X market split** — depends on
  hyperscaler adoption; Microsoft + Oracle + OpenAI
  are early Spectrum-X MRC adopters; Arista is the
  UEC-aligned alternative; final market share split
  is multi-year.
- **CPO adoption timing** — NVIDIA announced production
  2026 for Spectrum-X Photonics, but the broad
  adoption curve is 2027-2029. CPO eliminates the
  pluggable transceiver market for some switch
  platforms — material risk to LITE, COHR, Innolight
  traditional pluggable revenue.
- **Whether AVGO's custom ASIC business (Google TPU,
  Meta MTIA) is a durable 30%+ grower or if it
  plateaus** as hyperscalers diversify suppliers.

## 8. Momentum & direction

Direction over the last 6 months: **mixed, but net tightening
at the 1.6T / CPO layer**. The segment is bifurcated:

- **800G optical transceivers and switch ASICs (N5/N3):**
  loosening, as multiple suppliers have come on-stream
  (Innolight, Coherent, Lumentum at 800G DR8/FR4) and
  Broadcom Tomahawk 5 is in volume with multiple
  alternative vendors (Marvell Alaska, Cisco Silicon
  One G200) for the same sockets.
- **1.6T optical and Co-Packaged Optics (CPO):** still
  tightening, as this is the 2026 production-introduction
  wave. NVIDIA Spectrum-X Photonics (announced GTC March
  2025, production 2026) integrates optical directly with
  the switch ASIC, eliminating the pluggable transceiver
  layer for some switch platforms. 1.6T pluggable
  transceiver yield at Innolight, Coherent, Lumentum is
  the gating supply factor.

Leading indicators pointing toward net loosening:

- **UEC 1.0** spec released June 11, 2025; multi-vendor
  ecosystem (Arista, Cisco, Broadcom, Marvell) is bringing
  51.2-460 Tbps switch generations to market in 2026.
  Open standards are pulling demand toward the Ethernet
  fabric, which has more supply headroom than NVIDIA's
  proprietary NVLink + Spectrum-X.
- **Optical transceiver ASP** has stabilized at 800G
  (the 1.6T is by-allocation but the 800G has shifted
  from tight to balanced).

Leading indicators still pointing toward tightening at 1.6T /
CPO:

- **1.6T qualification yields** at all four major
  transceiver suppliers (Innolight, Coherent, Lumentum,
  Eoptolink) are still ramping; sell-side channel
  checks suggest yields in the 60-75% range at the
  start of 2026, which is a real constraint.
- **NVIDIA Spectrum-X Photonics** production volume
  targets for 2026 imply that 30-40% of NVIDIA's
  switch-attach optical will move to CPO by year-end
  2026, a step-function change.

`B'` reading (subjective, 6mo backward look): **roughly
-5 to +5** at the segment level. The bifurcation means
we should track 1.6T optical separately from 800G optical
in the scoring engine; the segment-level aggregate is
near-zero momentum.

## 9. Resolution timeline

The binding relief valves:

- **1.6T transceiver yield ramp** at Innolight, Coherent,
  Lumentum, Eoptolink — expected to reach the high-80s%
  by year-end 2026, removing the per-unit yield constraint
  on 1.6T pluggable deployment.
- **Coherent / Lumentum / Innolight capacity expansion** —
  all three announced 30-50% capacity expansions for
  2026 (1.6T and 800G combined); first waves of new
  capacity are online now, full effect H2 2026.
- **TSMC N3 capacity for switch ASICs** — Tomahawk 5,
  Marvell Alaska, Cisco Silicon One G200 are all N5/N3
  parts; as TSMC 3nm capacity eases (see
  `advanced-node-fabs.md`), the switch ASIC supply
  constraint also eases. Sub-effect: the wafer capacity
  is already largely there, the gating factor is
  substrate / advanced packaging (see
  `advanced-packaging.md`).
- **CPO production at scale** — NVIDIA Spectrum-X
  Photonics production ramps H2 2026; Broadcom and
  Marvell CPO products follow 2027. CPO eliminates the
  pluggable transceiver market for some switch
  platforms but supplies its own CPO-specific
  integrated laser / silicon photonics supply chain
  (Coherent, Lumentum, Corning as named partners).
- **NVIDIA ConnectX-8 and BlueField-4** ramp H2 2026
  adds SuperNIC supply; this eases the per-GPU
  networking attach constraint.

Demand-side relief:

- **NVL72 pod architecture** keeps the per-GPU networking
  ratio high (~9 NVSwitches per 72-GPU pod); this is
  structural and does not relax.
- **Ethernet vs. InfiniBand mix** — as UEC-aligned
  Ethernet matures, hyperscalers may shift a portion of
  AI networking from InfiniBand to Ethernet; this is
  supply-elastic (more Ethernet vendors) but a slow
  transition.

ETA bucket: **12-24 months** for full resolution at
the 1.6T / CPO layer. The 800G layer is closer to
STABLE; the CPO transition creates a 2026-2027
churn window.

## 10. Regime call

**Regime: PEAKING** for 1.6T / CPO specifically;
**STABLE** for 800G / N5-class switch ASICs; net
**PEAKING** for the segment with a 1.6T-specific
sub-regime label.

Confidence: **Medium**. The segment-level call is
directionally clear (mildly tightening at the 1.6T
layer, loosening at the 800G layer), but the timing
of the CPO transition creates a 2026 inflection
uncertainty. The scoring engine should track the
1.6T and 800G sub-layers separately and not collapse
them into a single segment-level B / B' read.

This segment is **NOT** in RESOLVING, so it remains
fully eligible for the long basket.

Watch-items that would flip the regime: (a) 1.6T
transceiver yield improvement acceleration, (b) CPO
production slip, (c) hyperscaler networking mix
shift (more Ethernet, less InfiniBand), (d) any
Broadcom / Marvell / Cisco market-share surprise
at the switch-ASIC layer.
