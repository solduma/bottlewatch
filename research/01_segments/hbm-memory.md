# HBM Memory

## 1. Definition & boundary (NAICS)

- **NAICS 3344** (Semiconductor and Related Devices Manufacturing),
  sub-segment **334413B** (Memory chips, including DRAM and stacked
  variants). HBM is a specialized DRAM stack — 8-Hi, 12-Hi, 16-Hi —
  vertically integrated using TSVs.
- Covers **HBM3, HBM3E, HBM4, and HBM4E** in production or pre-production.
  Excludes commodity DDR5, LPDDR5, GDDR6, and NAND.
- Includes the base DRAM wafer (1y/1z/1c node), the TSV bonding
  process, and the final stacked + tested HBM product.

## 2. Demand drivers (with units)

- **AI accelerator attach rate** — every NVIDIA H100 / H200 / B100 /
  B200 / GB200 ships with HBM3E (12-Hi 288GB on Blackwell Ultra).
  HBM per GPU rising from 80GB (H100) to 192GB (B200) to 288GB
  (Blackwell Ultra) to 384GB+ (Rubin).
- **2025 HBM market size** — ~$30-35B (estimate, BofA / Counterpoint
  consensus).
- **2026 HBM market size** — ~$54.6B (BofA estimate), +58% YoY.
- **HBM4 adoption** — ramps in H2 2026 with NVIDIA Rubin, AMD
  MI400/MI450, Google TPU v7p/v7e, AWS Trainium 3.
- **Hyperscaler ASIC demand** — Google TPU, AWS Trainium, Microsoft
  Maia all use HBM stacks; share of total HBM demand rising
  meaningfully.
- **2026 total HBM shipment estimates** — SK hynix 18-19 BGb,
  Samsung 15-16 BGb, Micron 6-6.5 BGb (BofA / Counterpoint).

## 3. Supply side: capacity, lead times, utilization

- **SK Hynix (000660.KS)** — HBM market leader with **~57-64% share
  in 2025** (revenue-based, Counterpoint). HBM3E in volume for NVIDIA
  Blackwell; HBM4 mass production secured September 2025. UBS
  projects hynix at **~70% of NVIDIA Rubin HBM4 supply** in 2026.
  Cheongju M15X fab first clean room completion targeted May 2026
  for HBM3E + HBM4.
- **Samsung Electronics (005930.KS)** — ~25-35% share. Lost NVIDIA
  HBM3 qualification in 2023, partial recovery on HBM3E in 2024-2025
  (qualified for Google TPU v7p/v7e), pushing to qualify HBM4 in
  2026.
- **Micron Technology (MU)** — ~10-20% share. HBM3E in volume for
  NVIDIA Blackwell; HBM4 in qualification for Rubin.
- **Lead time** — effectively allocated 12-18 months forward, similar
  to CoWoS. HBM ASP has been rising in 2024-2025 as demand outstrips
  supply.
- **HBM ASP** — estimate ~$15-20/GB for HBM3E 8-Hi, higher for
  12-Hi; HBM4 expected to be similar or modestly higher at launch.

## 4. Chokepoints

- **Three-vendor concentration** — only SK hynix, Samsung, and
  Micron produce HBM. SK hynix's lead is the result of a 3-year
  early bet on TSV manufacturing. New entrants (CXMT in China)
  are 2-3 years behind.
- **Base DRAM wafer capacity** — HBM consumes ~3x the wafer area
  of a standard DDR5 die (because of TSV keep-out zones and the
  larger die footprint per stack height). HBM ramp has tightened
  the overall DRAM supply curve in 2024-2025.
- **TSV process know-how** — the single hardest step; yield
  improvements have been the gating factor in HBM3E 12-Hi
  ramp.
- **Regulatory** — US BIS HBM export controls (Dec 2024 update)
  extended restrictions to HBM specifically, capping China's
  access to advanced memory.
- **HBM4 design challenges** — custom base die for NVIDIA Rubin
  (logical die designed by NVIDIA, manufactured at a foundry);
  HBM4 also moves to a 2048-bit interface (vs. 1024-bit on
  HBM3E), requiring more complex PHY integration on the
  host ASIC.

## 5. Public players

- **SK Hynix (000660.KS)** — pure-play HBM exposure (HBM is ~30-40%
  of revenue at current mix, growing); HBM is the highest-margin
  product line.
- **Samsung Electronics (005930.KS)** — HBM is a smaller mix of
  total revenue (~5-10%) but is the upside call.
- **Micron Technology (MU)** — HBM is a growing slice of DRAM
  revenue (~15-25% of DRAM in FY2026 by some estimates).
- **Western Digital / Sandisk** — not exposed to HBM.
- **Rambus (RMBS)** — HBM PHY IP licensor; small-cap, leveraged
  to HBM attach rate growth.
- **ASMPT (0522.HK)** — TSV bonder supplier (HBM-specific
  equipment).
- **Kulicke & Soffa (KLIC)** — adjacent equipment.

## 6. Lead indicators (track daily/weekly)

- **SK Hynix quarterly HBM revenue** — disclosed in earnings
  call, the cleanest read on HBM pricing and volume.
- **DRAM spot price** (DDR5, DDR4) — proxy for memory cycle;
  HBM pricing loosely tracks overall DRAM.
- **Hyperscaler HBM attach language** — quarterly earnings calls
  (NVIDIA commentary on HBM3E supply, AMD on HBM4 ramp).
- **HBM4 qualification announcements** — supplier press releases
  on NVIDIA / AMD / Google qualifications.
- **Bonder equipment orders** — ASMPT, Kulicke & Soffa order
  commentary; leading indicator for HBM capacity 9-12 months
  out.
- **BIS export control updates** — Federal Register notices
  on HBM-specific restrictions.

## 7. Open questions / data gaps

- **Exact HBM4 allocation** between SK hynix, Samsung, Micron
  for NVIDIA Rubin — Samsung has not yet announced HBM4
  qualification with NVIDIA, and the timing of that
  qualification is the single largest 2026 variable for the
  segment.
- **HBM4 ASP** — sell-side estimates vary $15-25/GB depending on
  configuration (12-Hi vs. 16-Hi).
- **Long-term HBM cycle** — some analysts see an ASP correction
  in 2027-2028 as Samsung catches up and SK hynix's M15X ramps;
  others see continued tightness into 2028. Mark as TBD pending
  cycle evidence.
- **HBM4E (2027-2028) timeline** — JEDEC standard still in
  drafting; not enough visibility to assign conviction.

## 8. Momentum & direction

Direction over the last 6 months: **tightening further, not
plateauing**. The HBM segment is the most aggressive PEAKING
segment in the entire value chain as of mid-2026. Leading
indicators pointing toward further tightening:

- **HBM ASP** has continued to rise through 2025-2026; sell-side
  channel checks suggest HBM3E 12-Hi ASP is now $20-25/GB,
  up from $15-20/GB in 2024. HBM4 launch pricing has been
  guided 10-15% above HBM3E 12-Hi.
- **Per-GPU HBM content** is the dominant demand driver: B200
  (192GB) → Blackwell Ultra (288GB) → Rubin (384GB+) is a
  ~2x increase in HBM die area per accelerator unit over
  24 months.
- **Hyperscaler ASIC demand** — Google TPU v7p/v7e, AWS
  Trainium 3, Microsoft Maia 2 are all HBM4-class products
  with attach rates of 8-Hi and 12-Hi; their 2026-2027
  ramps are additive to the NVIDIA Rubin demand, and were
  not fully reflected in the original HBM capacity build-out
  plans of 2023-2024.
- **Samsung HBM4 qualification** with NVIDIA has slipped
  from "late 2025" to "no public date"; this keeps the
  market structurally tight (effectively 2-vendor rather
  than 3-vendor through 2026).

Leading indicators that argue against further escalation:

- **SK hynix M15X** Cheongju fab is on schedule for first
  clean room completion May 2026 and HBM4 mass production
  in H2 2026. This is the single largest HBM capacity
  addition in 2026.
- **Micron** has publicly committed to HBM4 qualification
  with NVIDIA for Rubin (H2 2026); a successful qualification
  would add 15-20% to the available HBM4 supply.

`B'` reading (subjective, 6mo backward look): **roughly +10
to +20** (still tightening, the rate of tightening has
decelerated but the segment is not yet plateauing). This is
the highest `B'` in the entire value chain along with CoWoS.

## 9. Resolution timeline

The binding relief valves:

- **SK hynix M15X** (Cheongju, Korea) — first clean room
  completion May 2026, HBM4 mass production H2 2026. Adds
  an estimated 15-18k wafers/month of HBM-equivalent DRAM
  capacity by year-end 2026 (after TSV yield ramp). M15X
  is the load-bearing 2026-2027 supply event.
- **SK hynix M16** (Yongin, Korea) — first phase under
  construction; targeted for 2027 commissioning. M16 is the
  2027+ supply event.
- **Samsung HBM4 qualification** with NVIDIA — still TBD;
  the timing of this is the single largest 2026 variable
  for the segment. If Samsung qualifies H1 2026, it absorbs
  ~15-20% of NVIDIA Rubin HBM4 demand and meaningfully
  loosens the market. If it slips to 2027, the segment
  remains structurally tight.
- **Micron HBM4 ramp** — H2 2026 targeted; adds ~10-15% to
  HBM4 supply at full ramp.
- **CXMT (China)** — HBM3-equivalent in development; 2-3
  years behind, not a 2026-2027 relief valve.
- **HBM4E (16-Hi and beyond)** — JEDEC standard still in
  drafting; supplier prep 2026-2027; not a 2026 capacity
  event.

Demand-side relief:

- **Hyperscaler ASIC mix shift** — hyperscalers may use
  HBM3E for non-frontier inference (cost optimization),
  freeing HBM4 for frontier training. This is a marginal
  effect.
- **Neocloud funding slowdown** — modest; ~5% reduction
  in implied HBM demand at the margin.

ETA bucket: **12-24 months** for meaningful resolution. The
SK hynix M15X ramp + Samsung HBM4 qualification (if on
schedule) + Micron HBM4 ramp bring the aggregate HBM market
to STABLE by H2 2027. Until then, the segment is supply-
allocated and ASP-driven.

## 10. Regime call

**Regime: PEAKING** (segment tightness still in the upper
range; rate of tightening has decelerated but not yet
reversed).

Confidence: **High**. This is the cleanest PEAKING call in
the value chain. The combination of (a) record ASPs, (b)
per-GPU HBM content still rising, (c) Samsung HBM4
qualification still pending, (d) hyperscaler ASIC demand
additive — all argue for PEAKING rather than PEAKED or
RESOLVING. Confidence is highest on this segment because
the supply-side relief pipeline is well-known (M15X, M16,
Micron, Samsung) and none of the named events have
commenced.

This segment is **NOT** in RESOLVING, so it remains fully
eligible for the long basket. For the short basket, B × |B'|
ranks it among the highest in the value chain.

Watch-items that would flip the regime: (a) Samsung HBM4
qualification with NVIDIA, (b) M15X ramp delay, (c) Rubin
launch delay. Any of these would shift the regime toward
PEAKED → RESOLVING over a 6-12 month window.
