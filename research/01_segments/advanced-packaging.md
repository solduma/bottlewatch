# Advanced Packaging (CoWoS / 2.5D / 3D)

## 1. Definition & boundary (NAICS)

- **NAICS 3344** (Semiconductor and Related Devices Manufacturing),
  sub-segment **334413A** OSAT (Outsourced Semiconductor Assembly
  and Test) plus the in-house advanced packaging line at foundries
  (TSMC CoWoS / SoIC).
- Covers **2.5D interposer-based packaging** (CoWoS-S, CoWoS-R,
  CoWoS-L, Intel EMIB), **3D stacked die** (TSMC SoIC, AMD 3D
  V-Cache, Samsung X-Cube), and **chiplet integration substrates**
  (ABF-based). Excludes traditional wire-bond QFN/BGA packaging.

## 2. Demand drivers (with units)

- **AI accelerator volume** — every NVIDIA H100/H200/B100/B200/GB200
  ships in a CoWoS-S or CoWoS-L package. NVIDIA consumes ~60% of
  TSMC's CoWoS capacity. AMD MI300/MI325/MI400 use CoWoS-S.
- **2024 CoWoS wafer demand** — ~37-40k wafers/month.
- **2025 CoWoS wafer demand** — ~65-75k wafers/month (target).
- **2026 CoWoS wafer demand** — ~90k+ wafers/month (target).
- **Apple Silicon** — A-series and M-series move to advanced packaging
  (integrated fan-out, CoWoS variants for M3 Ultra / M4 family).
- **AMD Instinct MI400/MI450** — HBM4 + CoWoS in 2026-2027.

## 3. Supply side: capacity, lead times, utilization

- **TSMC CoWoS** — the dominant supplier; capacity ramp has been the
  single most-watched number in the AI supply chain in 2024-2025.
  TSMC management has stated the 2025 target multiple times; supply
  still tight. Customers receive **allocation, not market price**.
- **ASE Technology (ASEH)** — 2nd largest OSAT, advanced packaging
  share; competes in fan-out wafer-level packaging (FOWLP) and
  selected 2.5D.
- **Amkor Technology (AMKR)** — major OSAT, expanding advanced
  packaging capacity; new Arizona facility for Apple silicon.
- **SPIL (Siliconware Precision, part of ASE)** — sub-tier OSAT.
- **JCET (600584.SS)** — leading Chinese OSAT; advanced packaging
  capability in 2.5D and fan-out.
- **Powertech Technology** — memory packaging; some HBM backend.
- **Lead time** — for advanced packaging, lead time is meaningless;
  capacity is allocated 12-18 months forward. Substrate lead times
  (ABF from Ibiden/Shinko/Unimicron) are the next binding layer,
  with published lead times 3-6 months for non-AI demand and
  effectively "by allocation" for AI.

## 4. Chokepoints

- **Single-vendor risk (TSMC CoWoS)** — CoWoS is a TSMC proprietary
  flow. ASE and Amkor have competing 2.5D flows (TSV-less
  interposers, fan-out bridge) but they have not yet qualified at
  NVIDIA scale. Intel's EMIB is a viable alternative architecture
  but capacity is constrained.
- **ABF substrate supply** — Ibiden, Shinko, Unimicron, AT&S are the
  four major ABF makers. Capacity has been a multi-year chokepoint;
  Ibiden has been investing in new lines but ramp takes 2-3 years.
- **Interposer supply** — large-area silicon interposers for
  CoWoS-L are themselves a low-yield product; bumping interposer
  area beyond the reticle limit is one of the engineering
  challenges.
- **Bumping / UBM** — Tanaka and MKE for under-bump metallization.
- **Test capacity** — advanced package test (KGD / known-good-die
  test, HBM stack test) is its own capacity chokepoint; Teradyne
  and Advantest are the suppliers.

## 5. Public players

- **TSM** (TSMC, Taiwan) — CoWoS / SoIC in-house; dominant AI
  exposure; 60-70% of segment revenue is CoWoS-related when
  including adjacent flows.
- **ASEH** (ASE Technology, Taiwan) — pure-play OSAT, ~40-50%
  exposure; broad mix dilutes pure AI exposure.
- **AMKR** (Amkor, US-listed) — OSAT with growing AI exposure;
  ~25-35% pure-play exposure to advanced packaging.
- **IPGP** (IPG Photonics, US) — adjacent (laser processing for
  advanced packaging).
- **Teradyne (TER)** and **Advantest (6857.JP)** — test
  equipment; ~10-15% revenue from advanced packaging test.
- **Ibiden, Shinko, Unimicron, AT&S** — substrates (covered in
  `tnd` / `pkg_substrates` in the value chain; exposure to
  these companies is via their substrate business lines).

## 6. Lead indicators (track daily/weekly)

- **TSMC CoWoS monthly wafer-out** — TSMC monthly revenue is the
  proxy; CoWoS is not separately disclosed but commentary on
  quarterly calls is informative.
- **NVIDIA Blackwell / Rubin ramp commentary** — quarterly
  earnings calls; supply-side language ("supply-constrained
  through CY26" vs. "tracking demand").
- **ABF substrate order book** — Ibiden, Shinko, Unimicron
  earnings calls (quarterly).
- **HBM stack test equipment orders** — Teradyne, Advantest
  orders commentary.
- **CoWoS-L yield** — supply-chain notes (DigiTimes, SemiAnalysis,
  Reuters).
- **Amkor Arizona / Korea advanced packaging capex** — quarterly
  capex disclosure is a leading indicator for capacity 18-24
  months out.

## 7. Open questions / data gaps

- **CoWoS-L interposer yield** at the larger reticle sizes needed
  for Rubin — TSMC has not publicly disclosed yield curves.
- **ABF substrate allocation** between NVIDIA, AMD, and
  hyperscaler ASICs in 2026 — Ibiden/Shinko/Unimicron disclosure
  is aggregate; AI allocation is inferred.
- **The competitive trajectory of Intel EMIB / Foveros** in
  winning hyperscaler ASIC packaging business — to date,
  capacity is constrained and most leading-edge AI flows route
  through TSMC.
- ASE's **fan-out bridge** (ViA) as a CoWoS alternative — has
  not yet been qualified at NVIDIA scale; upside optionality.

## 8. Momentum & direction

Direction over the last 6 months: **plateauing, not yet
loosening**. CoWoS supply remains allocated 12-18 months forward,
but the rate of incremental tightening has slowed. Leading
indicators pointing toward plateauing:

- **TSMC management commentary** on Q1 2026 earnings reaffirmed
  the 2026 CoWoS target of ~90k wafers/month (up from ~65-75k
  in 2025) but did not raise it, which is a sign that the
  previously aggressive ramp is hitting the yield / equipment /
  substrate pace constraints.
- **ABF substrate order book** at Ibiden, Shinko, Unimicron
  remains sold out, but Ibiden's new line (Yokkaichi Phase 3)
  is on schedule for H2 2026 commissioning, providing some
  forward visibility on substrate relief.
- **Amkor Arizona** is now in volume production for Apple
  Silicon packaging (the "Amkor/Apple TSMC-Arizona-Phoenix
  cluster") — a meaningful second source of US advanced
  packaging capacity.

Leading indicators still pointing toward tightness:

- **NVIDIA Rubin tape-out and ramp timing** — Rubin is a
  CoWoS-L product (larger interposer than Blackwell); the
  2026 ramp is forecast to consume 30-40% more interposer
  area per package than Blackwell. This is a per-unit
  intensification of the bottleneck.
- **Hyperscaler ASIC volume** — Google TPU v7p/v7e, AWS
  Trainium 3, Microsoft Maia 2 all require CoWoS-S or
  CoWoS-L; their 2026 ramps are additive to NVIDIA Rubin
  demand and were not in the original 2025 CoWoS targets.

`B'` reading (subjective, 6mo backward look): **roughly -5 to
+5** (essentially flat to marginally positive — the supply
addition is keeping pace with demand, neither side winning
decisively). The segment is in a **plateau**, not a peak-and-
decline.

## 9. Resolution timeline

The binding relief valves:

- **TSMC CoWoS-L capacity ramp** — Kaohsiung AP6 + AP7 fabs
  commissioning through 2026; AP7 specifically is the
  dedicated CoWoS-L line for NVIDIA Rubin-class products.
  AP7 Phase 1 first wafers targeted Q3 2026, full ramp
  through 2027. AP7 is the single most-watched commissioning
  event in the segment for 2026-2027.
- **TSMC AP3 (Hsinchu) and AP5 (Taichung)** — both at
  higher utilization; targeted to add 10-15k wafers/month
  combined by year-end 2026 through equipment density
  improvements (more wpm per existing footprint).
- **Amkor Arizona** — Phase 2 advanced packaging ramp Q3
  2026 adds ~5-7k wafers/month equivalent of US advanced
  packaging capacity (Apple-focused initially, but
  Apple is no longer the binding customer).
- **Amkor Korea (Cheonan) and Amkor Vietnam** — additional
  ~5-8k wafers/month equivalent of advanced packaging
  capacity through 2026.
- **ASE Kaohsiung (K12B)** — first advanced packaging line
  in volume from Q1 2026; ~3-5k wafers/month by year-end.
- **Ibiden / Shinko / Unimicron ABF expansion** — Ibiden
  Yokkaichi Phase 3 commissioning H2 2026; Shinko Jisso
  lineup expansion Q3 2026; Unimicron capacity through
  2026. Combined ~15-20% increase in ABF substrate supply
  by year-end 2026.
- **Intel EMIB / Foveros** — Intel's 18A packaging capacity
  is ramping in parallel; Microsoft Maia and the US
  Department of Defense are the named customers so far,
  but Intel could capture a non-trivial share of hyperscaler
  ASIC packaging in 2026-2027.

Demand-side relief:

- **Hyperscaler capex moderation** — none yet in 2026.
- **Neocloud funding slowdown** — modest, 6-12 month delays
  on some neocloud GPU orders; ~5% reduction in implied
  CoWoS demand at the margin.

ETA bucket: **>24 months** for full resolution. The CoWoS-L
specific tightness (Rubin-era) extends the segment's tightness
well into 2027, and the ABF substrate layer adds another 6-12
months of relief lag. The segment is **NOT** in a resolution
phase — it is in a plateau that will not break for 24+ months.

## 10. Regime call

**Regime: PEAKING** (segment tightness still in the upper
range, but the rate of tightening has stalled; the binding
constraint has shifted from "any advanced packaging" to
specifically "CoWoS-L with large interposer, for Rubin-class
products").

Confidence: **High** on the call that this is PEAKING rather
than PEAKED. The CoWoS-L / Rubin-specific intensification
combined with the AI capex backdrop means the segment
tightness is not yet declining in absolute terms. The plateau
character of the last 6 months argues against a PEAKING → PEAKED
transition in the next quarter, but it also argues against
further significant tightening.

This is the single most important segment in the
**long-basket hard guard** framework: it is NOT in RESOLVING,
so it remains fully eligible for the long basket. B × |B'|
ranks it high because B is near peak and B' is near zero
(plateau = high B with non-trivial |B'| signal).

Watch-items that would flip the regime: (a) AP7 commissioning
delay past Q4 2026, (b) Rubin launch slip into 2027, (c) a
surprise drop in hyperscaler ASIC demand. None currently
flagged.
