# Rack-Scale Integration

## 1. Definition & boundary (NAICS)

- **NAICS 3341** (Computer and Peripheral Equipment Manufacturing)
  for integrated rack systems; **NAICS 4236** (Electrical and
  Electronic Goods Merchant Wholesalers) for the integration /
  distribution layer.
- Covers **rack-level integration** of GPU/ASIC systems, including
  NVIDIA HGX / DGX / NVL72, Supermicro rack-scale products,
  Dell PowerEdge XE racks, and the thermal / power / fabric
  integration that turns a box of GPUs into a deployable
  AI-cluster rack.
- Excludes pure server OEM/ODM (covered in
  `systems-rack-scale.md`); the distinction is the
  integration layer: rack-scale includes liquid cooling
  plumbing, busbars, NVLink switch trays, fabric management,
  and the rack-level power shelf (the "8 of the 12 kW
  per GPU" ecosystem).
- Vertiv, Schneider, and the CDU / busbar / power-shelf
  suppliers (Boyd, CoolIT, Asetek, Eaton, ABB) are the
  central physical-infrastructure integrators.

## 2. Demand drivers (with units)

- **NVL72 rack shipments** — ~25-30k racks in 2025; ~50-70k
  in 2026 (estimate).
- **Rack power density** — 40-50 kW/rack for HGX H100, 60-80
  kW for GB200 NVL72, 100-130 kW+ targeted for the next
  generation (Rubin-era). Air cooling breaks at ~40 kW; liquid
  cooling is the gating architecture for >50 kW racks.
- **Liquid cooling market** — ~$3.6B in 2024 → projected
  ~$15B by 2029 (CAGR ~30%).
- **Vertiv Q3 2025 backlog** — $9.7B (the company's record;
  AI-driven). Source:
  [fierce-network.com](https://www.fierce-network.com/cloud/ai-demand-drove-q3-2025-vertiv-earnings-backlog-hits-9-7b).
- **Schneider Electric data center liquid cooling revenue**
  — not separately disclosed but mentioned as a key growth
  driver in 2025 IR materials.

## 3. Supply side: capacity, lead times, utilization

- **Vertiv Holdings (VRT)** — Liebert XDU CDU, precision
  cooling, power distribution; Q3 2025 backlog $9.7B; AI
  is the single largest demand vector.
- **Schneider Electric (SU.PA)** — EcoStruxure for Data
  Centers, CDU, busbar systems; growing AI exposure.
- **Boyd (private)** — cold plates, heat exchangers, full
  liquid cooling systems; expanding capacity 2024-2025.
- **CoolIT Systems (private)** — direct-to-chip CDUs; OEM
  partnerships with SMCI, Dell, HPE.
- **Asetek (ASETEK.OL)** — DTC liquid cooling; pivoting to
  pure-play data center post-divestiture of gaming/gamer
  segment.
- **Eaton (ETN), ABB, Schneider, Vertiv** — busbar and
  power shelves; 800V DC architectures are emerging.
- **NVIDIA HGX / DGX / NVL72** — the dominant rack-scale
  reference platform; rack-scale revenue is part of NVIDIA's
  Data Center segment.
- **Lead time** — rack-scale systems are 6-12 months forward
  contracted. CDU delivery alone can be 3-6 months at
  peak allocation.

## 4. Chokepoints

- **CDU capacity** — the largest near-term physical
  chokepoint in 2025. Vertiv, CoolIT, Boyd, Asetek are
  the four major suppliers and all are capacity-constrained.
- **Quick-disconnect fittings and manifolds** — the
  unglamorous plumbing that fails first under scale.
  CPC, Parker, Festo are suppliers.
- **Coolant chemistry** — PG25 (propylene glycol) supply;
  propylene oxide / glycol capacity is a real constraint.
- **Power shelf + busbar capacity** — Eaton, ABB, Schneider,
  Vertiv; the 800V HVDC power shelf for next-gen NVIDIA
  racks is a 2026 ramp.
- **BMC / management plane** — AMI, NetBMC, OpenBMC; the
  firmware layer for rack-scale orchestration.
- **Standards fragmentation** — Open Rack V3 (Meta),
  NVIDIA MGX, OCP ORv3; no single standard yet.

## 5. Public players

- **VRT** (Vertiv Holdings, US) — pure-play AI data center
  thermal + power; ~80% data center exposure.
- **SU.PA** (Schneider Electric, France) — diversified
  energy management + data center; data center is ~30-40%
  of revenue.
- **ETN** (Eaton, US/Ireland) — electrical power
  management; AI data center is a growth driver.
- **ABB** (ABB, Switzerland) — busbar, switchgear, drives;
  AI data center exposure in power products.
- **NVDA** (NVIDIA, US) — rack-scale via HGX / DGX /
  NVL72 reference platforms.
- **SMCI** (Supermicro, US) — rack-scale products.
- **DELL** (Dell Technologies, US) — Dell Integrated
  Rack Scalable Infrastructure (IRSS).
- **GRC** (Global Rolled Cup, private / formerly listed) —
  liquid cooling; small-cap exposure if re-listed.
- **CoolIT (private)**, **Boyd (private)**, **Asetek
  (ASETEK.OL)** — private / small-cap.

## 6. Lead indicators (track daily/weekly)

- **Vertiv backlog (quarterly)** — $9.7B in Q3 2025 is the
  record; quarterly change is the cleanest leading indicator.
- **Schneider Electric data center segment commentary**
  — quarterly IR.
- **NVIDIA rack-shipment guidance** — quarterly, the upstream
  demand signal.
- **Hyperscaler capex guidance** — quarterly.
- **Eaton 800V HVDC design wins** — quarterly earnings
  commentary.
- **Liquid-cooling pricing** — channel checks; CDU ASP
  has been rising with allocations.

## 7. Open questions / data gaps

- **NVL72 versus Rubin-era rack architecture** — NVIDIA
  announced 800V HVDC for next-gen; the transition to
  800V inside the rack is a 2026-2027 capex cycle that
  will be visible in VRT, ETN, ABB revenue.
- **CDU supplier of the future** — as liquid cooling
  becomes a multi-MW architecture, will one supplier
  win out (Vertiv? CoolIT?) or will the market remain
  fragmented? Currently fragmented.
- **Liquid-to-liquid (L2L) versus liquid-to-air (L2A)
  CDUs at hyperscale** — L2L is the trend for >2 MW
  pods; this is favorable to Vertiv, Boyd, Schneider.
- **Immersion cooling adoption** — Microsoft has
  publicly committed to two-phase immersion at scale;
  Shell (S/390 immersion fluid), 3M (Novec), and the
  immersion cooling startups are sub-suppliers. Not
  a major 2025-2026 segment but a 2027+ watch item.

## 8. Momentum & direction

Direction over the last 6 months: **slightly loosening at
the CDU / thermal layer, plateauing at the busbar / 800V
HVDC layer**. The segment is a physical-infrastructure
mirror of the silicon segment, and is therefore driven
by the same upstream + downstream signals.

Leading indicators pointing toward loosening at the CDU
layer:

- **Vertiv Q3 2025 backlog** $9.7B was a record, but
  Q4 2025 / Q1 2026 commentary has shifted from
  "all-time backlog, sold out" to "backlog growing
  more slowly than bookings, lead times for new orders
  shortening." This is a typical plateau-to-loosen
  signature.
- **CDU capacity expansion** at Vertiv (Westerville OH
  + Lincoln NE), Boyd, CoolIT, Asetek is on schedule
  for 2026; first waves of new capacity are online now,
  with full effect H2 2026.
- **Liquid cooling pricing** has stabilized; channel
  checks suggest CDU ASPs are flat to slightly down
  vs. late 2025 peak.

Leading indicators still pointing toward tightening at
the busbar / 800V HVDC layer:

- **800V HVDC** is the load-bearing 2026-2027 capex
  cycle. NVIDIA announced 800V HVDC for Rubin-era
  racks, which is a step-function change in the rack
  power architecture. Eaton, ABB, Vertiv, Schneider
  are all in the early stages of capacity build-out.
- **Vertiv 800V HVDC product line** is in
  pre-production; full volume H2 2026.

`B'` reading (subjective, 6mo backward look): **roughly
-5 to -10** at the segment level. The segment is
plateauing and slightly loosening at the CDU layer,
but the 800V HVDC ramp prevents a clean PEAKED call
on the segment as a whole.

## 9. Resolution timeline

The binding relief valves:

- **CDU capacity expansion** at Vertiv, Boyd, CoolIT,
  Asetek — 30-50% aggregate capacity increase by
  year-end 2026.
- **800V HVDC power shelf** at Eaton, ABB, Vertiv,
  Schneider — first volume H2 2026, full ramp
  through 2027.
- **Liquid-to-liquid (L2L) CDU adoption** at hyperscale
  (>2 MW pods) — Vertiv, Boyd, Schneider are scaling;
  CoolIT and Asetek are also positioned.
- **Busbar capacity** at Eaton, ABB, Schneider, Vertiv
  is being expanded; first waves of new capacity H2
  2026.

Demand-side relief:

- **NVL72 pod growth** continues to drive per-rack
  CDU and busbar demand; structural and not relaxing.
- **Hyperscaler capex** unchanged; the rack-scale
  segment scales roughly with the GPU/ASIC segment.

ETA bucket: **12-24 months** for the CDU layer to
reach STABLE; **>24 months** for the 800V HVDC
layer, which is still ramping.

## 10. Regime call

**Regime: PEAKED** (CDU layer plateauing and starting
to loosen, with the 800V HVDC ramp as a sub-regime
that keeps the segment from going to RESOLVING for
another 12-24 months).

Confidence: **Medium**. The Vertiv backlog commentary
shift is a strong signal at the CDU layer, but the
800V HVDC ramp creates a 2026 inflection uncertainty.
The scoring engine should treat the CDU and 800V
HVDC sub-layers separately.

This segment is **NOT** in RESOLVING, so it remains
fully eligible for the long basket.

Watch-items that would flip the regime: (a) CDU
capacity ramp acceleration, (b) 800V HVDC product
launch slip, (c) any major liquid-cooling pricing
concession from Vertiv, Schneider, or Boyd, (d)
hyperscaler NVL72 ordering pause.
