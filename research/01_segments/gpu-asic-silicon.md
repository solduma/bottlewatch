# GPU / ASIC Silicon

## 1. Definition & boundary (NAICS)

- **NAICS 3344** (Semiconductor and Related Devices Manufacturing),
  sub-segment **334413D** (Fabless designers of GPUs, AI ASICs, and
  data-center accelerators).
- Covers **discrete GPU/ASIC silicon** for AI training and inference:
  NVIDIA (H100, H200, B100, B200, GB200, GB300, Rubin), AMD (MI300X,
  MI325X, MI400, MI450), Intel (Gaudi), and hyperscaler in-house
  ASICs (Google TPU, AWS Trainium, Microsoft Maia, Meta MTIA).
- Excludes CPU silicon (covered in `advanced-node-fabs.md`) and
  excludes FPGAs and embedded AI accelerators (covered in
  `networking-interconnect.md` where the design overlap is heavy).

## 2. Demand drivers (with units)

- **Training compute** — frontier model training clusters have
  scaled from 1k-10k GPUs (GPT-3 era, 2020) to 50k-100k (GPT-4,
  Llama 3, 2023-2024) to 100k-1M+ (2025-2026 frontier runs).
  Source: NVIDIA / hyperscaler disclosures, SemiAnalysis
  supply-chain estimates.
- **Inference compute** — large-scale inference (ChatGPT, Gemini,
  Copilot) consumes 2-5x the inference tokens of training
  tokens cumulatively. Inference-side silicon demand is now the
  larger absolute compute footprint.
- **Sovereign AI** — Saudi Arabia (Humain), UAE (G42), India
  (sovereign compute initiatives), EU (EuroHPC), Japan (METI
  GenAI infra), Korea (Naver / NHN Cloud) are all committing
  >$1B compute programs. Cumulative sovereign AI capex could
  reach $50-100B by 2027 (estimate, mostly public commitments).
- **2025-2026 NVIDIA revenue trajectory** — Q3 FY2026 (reported
  Q3 CY2025) data center revenue run-rate $30B+/quarter; total
  calendar 2025 ~$200B+ calendar year revenue range.
- **Hyperscaler ASIC volume** — Google TPU v7p/v7e, AWS Trainium 3,
  Microsoft Maia 2, Meta MTIA v3 — combined ~$15-25B in 2025,
  expected to scale to $40-60B by 2027.

## 3. Supply side: capacity, lead times, utilization

- **NVIDIA** — sole source of the GB200 NVL72 rack-scale system;
  dominant share (>85-90% by revenue) of accelerator silicon
  consumed by US hyperscalers in 2024-2025. Capacity is the
  product of TSMC wafer allocation × CoWoS allocation × HBM
  allocation; allocation rather than price clears the market.
- **AMD** — meaningful #2 in DC GPU; MI300X / MI325X in 2024-2025,
  MI400 / MI450 in 2026 (HBM4 era).
- **Intel (Gaudi)** — strategic effort; share remains small.
- **Hyperscaler in-house** — Google TPU, AWS Trainium, Microsoft
  Maia are real programs; Trained on TSMC N3/N5 and increasingly
  the 2nm node. ASICS are now a real alternative for non-frontier
  training and most inference workloads.
- **Lead time** — effectively allocated 12-18 months forward.
  Hyperscalers sign multi-quarter (sometimes multi-year)
  commitments to lock in capacity. NVIDIA's order book is now
  an analyst-tracked indicator.

## 4. Chokepoints

- **Three upstream gates in series** — wafer (TSMC) →
  packaging (TSMC CoWoS) → HBM (hynix/Micron/Samsung). A
  constraint at any one propagates; the binding constraint
  has shifted from HBM (2023) to CoWoS (2024-2025) and may
  shift back to HBM (2026) as HBM4 ramps.
- **Network fabric** — GB200/GB300 NVL72 depends on NVLink
  Switch; the scale-out fabric depends on Spectrum-X
  (NVIDIA) or UEC-compliant Ethernet (Arista, Cisco, Broadcom).
  See `networking-interconnect.md`.
- **Power delivery at the rack** — 800V DC architectures are
  emerging (NVIDIA announced 800V HVDC for Rubin-era racks);
  Onsemi, Monolithic Power, TI, Renesas are the key power
  silicon suppliers and a 2026-2027 capacity gate.
- **EDA + IP bottleneck** — Synopsys, Cadence, Arm are
  the three EDA / IP chokepoints. Some 2nm tape-out risk
  relates to EDA tool maturity for GAA + BSPDN (backside
  power delivery).

## 5. Public players

- **NVDA** (NVIDIA, US) — dominant share; ~95-100% pure-play.
- **AMD** (Advanced Micro Devices, US) — DC GPU + CPU; AI
  GPU is ~30-40% of revenue mix in 2025 and growing.
- **AVGO** (Broadcom, US) — custom AI ASIC (Google TPU,
  Meta MTIA partner, others) + networking; AI revenue
  disclosed at $20B+ run-rate by Q3 CY2025.
- **MRVL** (Marvell, US) — custom AI silicon (Amazon
  Trainium partner, others) + networking; AI revenue
  scaling.
- **GOOG** (Alphabet, US) — TPU program; in-house silicon
  consumed internally and via Google Cloud.
- **AMZN** (Amazon, US) — Trainium, Inferentia, Nitro
  silicon; in-house.
- **MSFT** (Microsoft, US) — Maia, Cobalt; in-house
  accelerator program at TSMC.
- **INTC** (Intel, US) — Gaudi (small share); foundry /
  IDM exposure to fab segment covered in
  `advanced-node-fabs.md`.

## 6. Lead indicators (track daily/weekly)

- **NVIDIA quarterly data center revenue** — reported quarterly;
  the single most-watched number in the AI economy.
- **Hyperscaler capex guidance** — MSFT, GOOG, AMZN, META
  quarterly; leading indicator for the 4-6 quarter silicon
  demand curve.
- **TSMC CoWoS wafer allocation** — commentary on quarterly
  calls.
- **HBM pricing** — see `hbm-memory.md`.
- **Networking fabric announcements** — Arista, Cisco,
  Broadcom earnings commentary on AI Ethernet.
- **Power delivery 800V design wins** — Advanced Energy
  + Onsemi, Monolithic Power earnings commentary.
- **Form 4 insider transactions** — clustering on the
  named tickers is a smart-money signal.

## 7. Open questions / data gaps

- **Hyperscaler ASIC unit share trajectory** — Google TPU
  + AWS Trainium + Microsoft Maia + Meta MTIA combined
  share of hyperscaler AI compute is growing but exact
  figures are not publicly disclosed. Estimate range
  10-20% of US hyperscaler AI compute in 2025,
  20-30% by 2027.
- **NVIDIA Rubin launch date and pricing** — Rubin was
  announced at GTC 2025; production volume expected H2
  2026; exact tape-out / launch date pending verification.
- **The 2nm + HBM4 + CoWoS-L triple overlap in 2026** —
  the simultaneous ramp of all three constraints will
  be a 2026-specific risk to monitor.
- **China / Huawei Ascend trajectory** — Huawei's Ascend
  910C / 910D are real but constrained by US export
  controls at 7nm/5nm; how the December 2024 BIS update
  plays out is a binary risk for the segment.

## 8. Momentum & direction

Direction over the last 6 months: **loosening at the
NVIDIA-frontier layer, plateauing at the hyperscaler-ASIC
layer, EMERGING at the inference / neocloud tier**. The
segment is structurally multi-tiered and the layers are
diverging.

Leading indicators pointing toward loosening at the
NVIDIA-frontier layer:

- **NVIDIA data center revenue** Q1 FY2027 (reported
  May 2026) showed the first sequential pause in
  growth since the H100 era — sell-side read this as
  the Blackwell Ultra → Rubin transition creating a
  short demand air-pocket, not a structural demand
  decline.
- **Hyperscaler capex** 2026 guidance (~$400B) is
  unchanged from prior, but the *mix* is shifting
  toward ASIC for non-frontier inference and toward
  neoclouds / sovereign AI for the next growth leg.
- **Hyperscaler ASIC attach rate** is rising: combined
  Google TPU + AWS Trainium + Microsoft Maia is now
  estimated at 15-25% of US hyperscaler AI compute,
  up from 10-20% a year ago (estimate, not publicly
  disclosed).

Leading indicators pointing toward tightening at the
hyperscaler-ASIC layer:

- **Google TPU v7p / v7e** ramp at TSMC N3, plus
  **AWS Trainium 3** at TSMC N3, plus **Microsoft Maia 2**
  at TSMC N3 — all competing for the same wafer
  capacity as the NVIDIA Rubin ramp.
- **Sovereign AI** is now a real demand vector: Saudi
  (Humain), UAE (G42), India, EU (EuroHPC), Japan (METI
  GenAI infra) all committing >$1B compute programs
  (cumulative estimate $50-100B by 2027).

`B'` reading (subjective, 6mo backward look): **roughly
-5 to -10** at the segment level, weighted to the
NVIDIA-frontier mix. The segment is past peak growth
rate but still at peak absolute spend.

## 9. Resolution timeline

The binding relief valves (segment-level — wafer, packaging,
HBM all covered in their own briefs):

- **NVIDIA Rubin ramp** H2 2026 — the next-generation
  accelerator; supply ramp tracks the 2nm + CoWoS-L +
  HBM4 triple ramp. Rubin is a 2026-2027 supply event,
  not a relief.
- **Hyperscaler ASIC diversification** — the structural
  shift toward in-house ASICs is itself the supply-side
  relief for the segment, because it pulls demand off
  the NVIDIA-frontier capacity. ASIC mix shift is
  continuous through 2026-2027.
- **Sovereign AI capex** — adds demand, not relief.
  Saudi (Humain), UAE (G42), India all have multi-GW
  site plans with first deliveries 2026-2027.
- **Neocloud funding slowdown** — CoreWeave's Q4 2025
  results showed customer concentration risk; some
  neocloud capex is pushing out 6-12 months. Modest
  demand-side relief.

Demand-side relief:

- **Hyperscaler capex moderation** — none yet in 2026.
  Watch 2027 guidance for the first signs of moderation.
- **Enterprise AI ROI questions** — the early-2026
  enterprise AI software results are mixed; some
  workloads (customer support, marketing copy) are
  showing disappointing ROI. This could moderate
  enterprise AI capex (a small fraction of total)
  through 2026-2027.

ETA bucket: **12-24 months** for the segment to reach
STABLE. The 2nm + CoWoS-L + HBM4 triple ramp in H2 2026
should add 20-30% to aggregate AI accelerator supply by
mid-2027, sufficient to absorb current demand without
further tightening but not enough to push the segment
into RESOLVING.

## 10. Regime call

**Regime: PEAKING** (NVIDIA-frontier plateau) transitioning
toward STABLE as the ASIC layer diversifies supply. The
segment is **NOT** in a single uniform regime — the
scoring engine should treat the three sub-layers
(NVIDIA-frontier, hyperscaler-ASIC, sovereign-AI/neocloud)
separately and compute a weighted aggregate.

Confidence: **Medium**. The segment is past peak growth
rate (B' is now slightly negative) but the absolute
spend level is still at record highs. The transition
from PEAKING to PEAKED over the next 6-12 months is the
base case, conditional on Rubin launching on schedule
and no hyperscaler capex cut.

This segment is **NOT** in RESOLVING, so it remains
fully eligible for the long basket. For the short basket,
B × |B'| is high but the regime is still PEAKING (not
RESOLVING-from-low or RESOLVING), so short-basket
inclusion is the dominant ranking signal here, not the
regime label itself.

Watch-items that would flip the regime: (a) hyperscaler
capex guidance cut for 2027, (b) NVIDIA Rubin launch
delay, (c) China export control enforcement
intensification, (d) any major sovereign AI project
cancellation.
