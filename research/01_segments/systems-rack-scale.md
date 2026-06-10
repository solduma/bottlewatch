# Systems OEM/ODM

## 1. Definition & boundary (NAICS)

- **NAICS 3341** (Computer and Peripheral Equipment Manufacturing)
  for server-level systems; **NAICS 3342** for network and
  communications equipment, but for integrated rack-scale
  systems the primary code is 3341.
- Covers **AI server OEMs** (Supermicro, Dell, HPE, Lenovo) and
  **AI server ODMs** (Foxconn / Hon Hai, Quanta, Wiwynn,
  Inventec, Wistron, Pegatron). The ODM / OEM split is a
  long-standing distinction: ODMs design + manufacture, OEMs
  brand + sell.
- Excludes **rack-scale integration** (covered in
  `rack-scale-integration.md`), but the boundary is fuzzy:
  Quanta and Foxconn participate at the rack-scale level for
  NVIDIA NVL72, and Supermicro has launched its own rack-scale
  products.

## 2. Demand drivers (with units)

- **AI server unit volume** — ~3-4M AI server units in 2025
  (estimate, multiple analysts), scaling to ~6-8M in 2026.
- **Hyperscaler AI capex** — combined 2026 capex guidance
  ~$400B; ~30-40% flows into compute hardware (silicon +
  systems + rack). Of that, systems is ~10-15% of total AI
  capex.
- **GB200 / GB200 NVL72 rack volume** — 2025 ~25-30k racks,
  2026 ~50-70k racks (estimate, multiple analysts).
- **Enterprise AI adoption** — Sovereign AI, mid-tier
  neoclouds, large enterprise (banks, telcos, pharma) are
  now ordering AI server fleets; SMCI, Dell, HPE are
  positioned here.

## 3. Supply side: capacity, lead times, utilization

- **Foxconn (Hon Hai, 2317.TW)** — leading ODM for GB200
  rack-scale with ~40-50% of NVIDIA's rack integration
  orders in 2025. Quanta is the other major ODM partner.
- **Quanta Computer (2382.TW)** — second major ODM partner
  for GB200 NVL36 / NVL72; significant AI server share.
- **Wiwynn (Wistron subsidiary, 6669.TW)** — third major
  ODM; strong in white-box AI server designs for
  hyperscalers and neoclouds.
- **Inventec (2356.TW)** — Tier 2 ODM; AI server
  participation.
- **Wistron (3231.TW)** — parent of Wiwynn; also direct
  ODM.
- **Supermicro (SMCI)** — pure-play AI server OEM;
  fastest-growing; rack-scale products (e.g., 4U/8U NVIDIA
  HGX-based) plus end-to-end liquid-cooled systems.
- **Dell Technologies (DELL)** — PowerEdge XE9680 +
  PowerEdge XE8640 for AI; high mix of NVIDIA HGX
  platforms.
- **HPE (HPE)** — Cray-based AI systems; ProLiant for
  general AI; smaller mix than Dell/Supermicro.
- **Lenovo (0992.HK)** — AI server growth in EMEA and
  Asia; smaller in US.
- **Lead time** — for NVIDIA GB200/GB300 rack-scale,
  customer contracts are 6-12 months forward; for
  traditional 8-GPU HGX servers, lead times are
  2-4 months.

## 4. Chokepoints

- **GPU allocation** — the binding upstream constraint
  on systems. Allocation flows from NVIDIA to OEMs/ODMs
  and they sell the integrated system.
- **Power supply capacity** — Delta, Lite-On, FSP,
  Advanced Energy are the four major PSUs; capacity is
  tight as 800V/48V platforms emerge. AE / Onsemi
  announced a 12kW SiC PSU reference design in 2025 for
  next-gen AI servers.
- **Chassis / metalwork** — Foxconn and Quanta are also
  the chassis suppliers; internal vertical integration.
- **Liquid cooling components** — for rack-scale
  systems, the chassis must integrate with CDU
  plumbing, which is a Vertiv / Boyd / CoolIT
  integration challenge.
- **Testing / validation** — for rack-scale systems,
  full-rack burn-in and validation is a 5-7 day
  process that is itself a capacity constraint.

## 5. Public players

- **SMCI** (Supermicro, US) — pure-play AI server OEM;
  ~80-90% AI exposure; market cap ~$30-40B (mid-2026
  estimate pending).
- **DELL** (Dell Technologies, US) — AI server is
  ~10-15% of revenue; PowerEdge XE series.
- **HPE** (Hewlett Packard Enterprise, US) — AI server
  ~5-10% of revenue; Cray heritage.
- **2317.TW** (Hon Hai / Foxconn, Taiwan) — ~30-40%
  revenue from servers / networking; AI is the growth
  vector.
- **2382.TW** (Quanta Computer, Taiwan) — ~70-80%
  server / networking; AI is the dominant share.
- **6669.TW** (Wiwynn, Taiwan) — pure-play hyperscale
  server ODM; ~80%+ AI exposure.
- **2356.TW** (Inventec, Taiwan) — diversified ODM
  with AI server exposure.
- **3231.TW** (Wistron, Taiwan) — parent of Wiwynn.
- **Pegatron (4938.TW)** — smaller AI server ODM.

## 6. Lead indicators (track daily/weekly)

- **NVIDIA GB200/GB300 shipment language** —
  quarterly earnings calls; the upstream signal.
- **Hyperscaler capex guidance** — quarterly; the
  downstream demand signal.
- **Foxconn / Quanta / Wiwynn monthly revenue** —
  published monthly in Taiwan (10th of month); the
  cleanest AI ODM leading indicator.
- **SMCI quarterly revenue + book-to-bill** — the
  cleanest pure-play AI server read.
- **DELL / HPE AI server revenue disclosure** —
  quarterly; less granular but still informative.
- **Delta Electronics monthly revenue** — published
  monthly; PSU demand signal.

## 7. Open questions / data gaps

- **Foxconn vs. Quanta vs. Wiwynn 2026 share split**
  — only directional information publicly available;
  exact allocation is disclosed in supply-chain notes
  (DigiTimes, Reuters) but not confirmed by NVIDIA
  or the ODMs.
- **Supermicro accounting / governance overhang** —
  the August 2024 Hindenburg report created a
  structural overhang on SMCI valuation; M0 should
  account for this in conviction sizing.
- **Vertical integration by NVIDIA** — NVIDIA's
  reference rack-scale designs increasingly encroach
  on ODM value-add. The structural question is whether
  ODMs remain at the same %-of-rack revenue as the
  AI build-out matures.
- **The 2-ODM versus 3-ODM world** — current buildout
  is Foxconn + Quanta + Wiwynn + SMCI. If
  consolidation happens (which it usually does in
  AI hardware), who wins?

## 8. Momentum & direction

Direction over the last 6 months: **plateauing at the
ODM layer, EMERGING at the rack-scale ODM + OEM
boundary**. The segment is a downstream of the GPU/ASIC
allocation and an upstream of the rack-scale integration,
so its regime is a function of the two adjacent
segments.

Leading indicators pointing toward plateauing at the
ODM layer:

- **Foxconn monthly revenue** Q1 2026 grew ~25% YoY in
  TWD terms but decelerated sequentially — consistent
  with the NVIDIA Blackwell Ultra → Rubin transition
  creating a short demand air-pocket (see
  `gpu-asic-silicon.md`).
- **Quanta monthly revenue** similar pattern.
- **Wiwynn monthly revenue** similar pattern; first
  quarter of YoY deceleration in 5 quarters.
- **SMCI book-to-bill** has moved from >1.5x in 2024
  to ~1.1-1.2x in Q1 2026; still positive but no longer
  in the "demand exceeds supply" zone.

Leading indicators pointing toward EMERGING at the
rack-scale ODM + OEM boundary:

- **Supermicro rack-scale products** are gaining
  share at the mid-tier (non-frontier inference).
- **Dell PowerEdge XE** rack-scale + IRSS offerings
  are gaining at enterprise (banks, telcos, sovereign
  AI).
- **ODM-direct hyperscaler ordering** for full-rack
  products (bypassing the OEM brand) is the
  structural trend; ODMs are capturing value.

`B'` reading (subjective, 6mo backward look): **roughly
0 to -5** at the segment level. The segment is at a
plateau; the EMERGING sub-trend at the rack-scale
ODM boundary is offsetting the plateau at the ODM
sled layer.

## 9. Resolution timeline

The binding relief valves are upstream — the segment
tightness is a function of GPU allocation, CoWoS
packaging, HBM, and 800V HVDC power shelves. The
segment itself does not have a binding capacity
constraint; the supply side scales with capex.

- **Foxconn + Quanta + Wiwynn + SMCI capex** for
  2026 is collectively up 20-30% YoY; the named
  ODMs are adding chassis / burn-in / integration
  capacity in line with the upstream ramp.
- **ODM consolidation** if it happens would
  actually tighten the segment for a quarter or
  two (typical post-merger integration friction)
  but would not be a structural relief event.

ETA bucket: **<12 months** for the segment to reach
STABLE, in lockstep with the upstream GPU/ASIC
allocation easing.

## 10. Regime call

**Regime: STABLE** (segment is at a plateau with no
clear directional signal; the EMERGING sub-trend at
the rack-scale boundary is a watch-item, not a
regime-level call).

Confidence: **Medium-High**. The ODM segment is
structurally a derivative of the GPU/ASIC segment
and does not have an independent tightness /
loosening dynamic. The scoring engine should treat
the ODM segment as a STABLE pass-through with mild
EMERGING signal at the rack-scale boundary.

This segment is **NOT** in RESOLVING, so it remains
fully eligible for the long basket — but it is also
not a PEAKING call, so B × |B'| ranks it lower than
the upstream GPU/ASIC, CoWoS, HBM segments for
short-basket purposes.

Watch-items that would flip the regime: (a) NVIDIA
shipment acceleration (would push ODM to PEAKING
again), (b) ODM consolidation announcement, (c)
hyperscaler direct-from-ODM bypassing (which would
shift value share but not regime).
