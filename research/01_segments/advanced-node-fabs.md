# Advanced-Node Fabs

## 1. Definition & boundary (NAICS)

- **NAICS 3344** — Semiconductor and Other Electronic Component
  Manufacturing. Subset: **334413** (Semiconductors and Related Devices
  Manufacturing) for wafer-foundry and IDM logic production.
- This brief covers **leading-edge logic foundry**: process nodes
  ≤ 5nm (N5, N4P, N3, N3P, N2, A16) and the DRAM base layers that
  feed HBM stacks. Mature nodes (28nm+) are out of scope.
- Excludes memory-only IDMs except for the DRAM base layer used in HBM
  (covered in `hbm-memory.md`).

## 2. Demand drivers (with units)

- **Hyperscaler AI capex** — combined 2026 capex guidance ~$400B vs.
  ~$300B in 2025, ~30-40% YoY growth. Roughly 50-60% flows into
  compute (silicon + systems + rack), of which the silicon layer
  (TSMC wafer revenue) is ~25-30%. Source: hyperscaler earnings
  transcripts and Reuters/Bloomberg summaries.
- **AI accelerator unit volume** — NVIDIA Blackwell + Rubin shipments
  expected to scale from ~3-4M units in 2025 to ~5-6M in 2026
  (estimate, multiple analysts).
- **Smartphone SoC leading-edge demand** — Apple's A20/A20 Pro (N2),
  MediaTek Dimensity (N2 tape-out Sep 2025), Qualcomm Snapdragon 8
  Gen 5 — combined ~250-300M units/year.
- **Training compute scaling** — frontier model training runs now
  consume 50-100k H100/B200 equivalents; the next generation (Rubin)
  targets 1M+ GPU clusters.

## 3. Supply side: capacity, lead times, utilization

- **TSMC** — Q3 2025 revenue ~$33.1B, **~71% global foundry market
  share** (excl. Samsung). 3nm + 5/4nm ~46% of revenue; 7/6nm ~14%.
  3nm capacity to nearly double in 2025 to ~120-140k wafers/month by
  year-end. 2nm in trial production mid-2025, mass production
  H2 2025; nearly fully booked through 2026 and into 2027. Wafer
  pricing on 2nm reportedly $30k+/wafer.
- **Samsung Foundry** — #2; struggling on 3nm yield, focusing on
  2nm GAA as a clean-slate play; aggressive pricing to win customers.
- **Intel Foundry** — #3 at mid-single-digit share; 18A (1.8nm) ramp
  in Arizona is the strategic bet, with Microsoft and Amazon AWS
  committed as anchor customers.
- **SMIC** — confined to ≥7nm by US export controls; strategically
  irrelevant to leading-edge AI silicon.
- **Lead times** — wafer starts are booked 12-18 months forward; the
  binding constraint is **CoWoS packaging throughput**, not wafer
  capacity per se (see `advanced-packaging.md`).

## 4. Chokepoints

- **Geo concentration** — Taiwan hosts ~90% of leading-edge logic
  capacity (TSMC). Cross-Strait policy risk is the load-bearing
  geopolitical chokepoint.
- **Water + power at fab** — TSMC's Taiwan fabs consume ~9% of
  national industrial water; the 2021 drought cut wafer-out by
  single-digit %. Power: Taiwan's grid is tight, and TSMC's
  Arizona/Japan fabs require local power agreements.
- **Single-vendor tools** — ASML is the only EUV scanner supplier.
  Any disruption (geopolitical, manufacturing defect, natural
  disaster at Veldhoven) propagates downstream within 6-9 months.
- **Regulatory** — US BIS export controls (Oct 2022, Oct 2023, Dec
  2024 updates) cap China's access to ≤16/14nm logic; HBM
  restrictions extend the same logic to memory.

## 5. Public players

- **TSM** (TSMC, Taiwan) — pure-play foundry leader, $550-600B USD-equiv
  market cap; ~95%+ exposure to this segment.
- **Samsung Electronics (005930.KS)** — memory + foundry + handsets;
  foundry is ~15-20% of revenue but the strategic AI exposure.
- **INTC** (Intel, US) — IDM + foundry; foundry is the AI upside bet,
  ~10-15% of revenue but expected to scale.
- **UMC** (United Microelectronics, Taiwan) — mature-node specialist;
  <5% exposure to leading edge.
- **GlobalFoundries** (private post-2021 IPO withdrawal) — out of
  scope; does not compete at leading edge.

## 6. Lead indicators (track daily/weekly)

- **TSMC monthly revenue** (published monthly, 10th of each month for
  prior month in USD) — direct read on leading-edge utilization.
- **Foundry market share quarterly tracker** — TrendForce / Counterpoint
  quarterly updates.
- **Wafer ASP** — sell-side channel checks; pricing power proxy.
- **3nm / 2nm yield reports** — DigiTimes, Reuters supply-chain notes.
- **TSMC capex guidance** — quarterly earnings call, the leading
  indicator for capacity 12-18 months forward.
- **Apple iPhone unit sell-through** — first customer of every new
  node, leading indicator for ramp.
- **Section 232 / BIS export control updates** — Federal Register,
  US BIS notices.

## 7. Open questions / data gaps

- **TSMC 2nm capacity allocation** for 2026 — full customer
  allocation (Apple, AMD, NVIDIA, MediaTek, Qualcomm, Broadcom)
  pending verification; only public figures are aggregate bookings
  and the 30k+ wafer ASP.
- **Intel 18A external customer revenue trajectory** — Microsoft and
  AWS are publicly named, but volume and pricing remain
  undisclosed.
- **Samsung 2nm GAA yield** — Samsung claims "mass production H2
  2025" but yield data has not been independently verified.
- The **wafer-out equivalent of HBM base layers** is not directly
  broken out of TSMC's revenue; analyst estimates for "HBM
  capacity in wafer terms" range 12-18k wafers/month equivalent
  for SK hynix base + ~5-7k for Micron.

## 8. Momentum & direction

Direction over the last 6 months: **loosening at the leading edge,
still tight at 2nm**. TSMC's 3nm utilization eased modestly through
Q1-Q2 2026 as Apple A19 / A19 Pro volume normalized and the second
wave of NVIDIA Blackwell Ultra allocations absorbed the freed
capacity; sell-side channel checks suggest 3nm is now operating in
the high-80s utilization band, down from mid-90s in late 2025.
Leading indicators pointing toward loosening:

- **TSMC monthly revenue** trended sideways in USD terms Jan-May
  2026 despite a strong NT$ tailwind, implying real volume was flat
  to slightly down — consistent with digesting the 2025 3nm surge.
- **Wafer ASP** on 3nm reportedly softened ~5-8% from the late-2025
  peak as Apple renegotiated its 2026 allocation.
- **Samsung 2nm GAA** yield has reached the low-20s% (per
  supply-chain notes), which is a credible second-source for
  non-frontier customers (Qualcomm, MediaTek) and pulls demand
  off TSMC.

Leading indicators still pointing toward tightness at 2nm:

- **2nm wafer pricing** at $30k+/wafer has held — no signs of
  concession.
- **Apple A20 / A20 Pro** N2 tape-out is on schedule, and Qualcomm
  Snapdragon 8 Gen 5 is now confirmed at N2 — both will pull 2nm
  capacity from H2 2026.
- **Intel 18A** external customer revenue remains a 2027 story, not
  a 2026 relief valve.

`B'` reading (subjective, 6mo backward look): **roughly -10 to -20**
(mildly loosening at the 3/4/5nm aggregate level, unchanged-tight at
2nm). Weighted to the segment's revenue mix, the segment is
slightly off its late-2025 peak.

## 9. Resolution timeline

The binding relief valves (in order of expected contribution to
2026-2027 wafer supply):

- **TSMC N2 (2nm) ramp** — trial production H1 2025, mass
  production H2 2025; ramp through 2026 adds an estimated 25-35k
  wafers/month of 2nm-class capacity by year-end 2026 (Hsinchu
  + Kaohsiung fabs). Single largest supply addition in the
  segment.
- **TSMC N3P / N3X capacity expansion** — Fab 21 (Arizona)
  Phase 2 commissioning late 2026 adds another 20-25k wafers/month
  of 3nm-class capacity, with first wafers targeted for year-end
  2026.
- **Samsung 2nm GAA** — mass production H2 2025 (claimed) with
  yield improvement through 2026; if yield reaches the high-30s%,
  Samsung could provide 10-15k wafers/month of 2nm capacity by
  year-end 2026 (mostly captured by Qualcomm, MediaTek, and
  internal Exynos).
- **Intel 18A** — Fab 52/62 (Arizona) ramp 2026-2027; Microsoft and
  AWS are anchor customers but external volume is small in 2026
  (~5-10k wafers/month, mostly Microsoft's custom silicon).
  Meaningful 2027+ contribution.
- **JASM (Japan Advanced Semiconductor Manufacturing, TSMC JV)**
  — JASM Phase 1 (Kumamoto, 12/16/22/28nm) opened Q4 2024; Phase 2
  (6/7nm) commissioning H2 2026 adds ~10-12k wafers/month. Mature
  node capacity, not leading-edge, but it frees TSMC Taiwan
  capacity for leading-edge.
- **ESMC (TSMC / Bosch / Infineon / NXP, Dresden)** — ground
  broken 2024, first wafers targeted late 2027. Not a 2026
  contributor.

Demand-side relief:

- **Hyperscaler capex moderation** — none yet in 2026; combined
  2026 capex guidance is still ~$400B, up from ~$300B in 2025.
- **Neocloud funding slowdown** — CoreWeave's Q4 2025 results
  showed customer concentration risk; some neocloud capex is
  pushing out 6-12 months but is a marginal effect.

ETA bucket: **12-24 months** for full resolution. The N2 ramp
plus Intel 18A's first external revenue should bring the
aggregate segment to STABLE by mid-2027; 2nm will remain
specifically tight into 2027.

## 10. Regime call

**Regime: PEAKED** (transitioning from PEAKING over the last 6
months, not yet RESOLVING because the segment is still above
mid-70s in B-level terms).

Confidence: **Medium-High**. The combination of 3nm loosening,
sustained 2nm tightness, and a clear 12-24 month relief pipeline
(N2 ramp, Samsung 2nm, Intel 18A first revenue) makes PEAKED the
highest-conviction call. Lower confidence than the HBM call (see
`hbm-memory.md`) because the 2nm-HBM4-CoWoS-L triple overlap in
2026 is an unresolved timing risk that could push the segment
back to PEAKING if any of the three ramps slips materially.

Watch-items that would flip the regime: (a) Intel 18A 2026 ramp
delay, (b) Samsung 2nm yield stagnation below 30%, (c) any TSMC
Arizona utility (water / power) disruption. None currently flagged
as imminent.
