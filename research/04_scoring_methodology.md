# Bottleneck Scoring Methodology — Bottlewatch v1

> Per plan §7. Score per segment on **0-100** (higher = tighter
> bottleneck), built from five sub-scores normalized to [0,1] over a
> 5-year rolling band, horizon-weighted, then summed. The output
> drives a "conviction basket" of 3-5 tickers per horizon, built
> off the universe's `exposure_pct × segment_score` ranking.

This document specifies: (1) the formula, (2) each sub-score
definition with its data source, (3) horizon weights, (4) the
basket construction rule, (5) a worked example for the top
conviction pick, and (6) a backtest plan.

---

## 1. The formula

For each segment `s` and each horizon `h ∈ {near, med, long}`:

```
B(s, h) = 100 * Σ_i w_i(h) * normalize_5y(s_i)
```

where `s_i` is the raw value of sub-score `i`, `normalize_5y` maps
the raw value to [0,1] using a 5-year rolling min/max band, and
`w_i(h)` is the horizon weight for sub-score `i` (the weights sum
to 1.0 within each horizon). The `100 *` factor scales the [0,1]
sum to a 0-100 score for readability.

**Properties of the formula:**

- **Bounded output**: every sub-score contributes at most `100 * w_i(h)`
  to the total, and `Σ w_i = 1`, so `B ∈ [0, 100]` always.
- **Horizon-aware**: near-horizon weights lead-time + capacity
  (today's problems); long-horizon weights geo + regulatory
  (structural problems).
- **Comparable across segments**: same normalization band length,
  same sub-score definitions, so a 78 in HBM and a 78 in transformers
  mean the same thing.
- **Auditable**: every score decomposes into a vector of 5
  sub-scores. A reader can disagree with one input and see the
  effect on the total.

**Edge cases** — explicit defaults:
- A sub-score with <2 years of history gets the median of the
  universe (0.5) until the band fills.
- A sub-score that's flat (no variation) is treated as `0.5`.
- A segment with all-zero sub-scores returns `B=0` (ample capacity).
- The score is **directional, not predictive**: we rank segments;
  we do not claim a particular B value "means" a 10% price move.

---

## 2. Sub-score definitions

Five sub-scores, all `normalize_5y`-clamped. Each is documented
with its **raw value**, **source(s)**, and the **direction**
(higher raw = tighter bottleneck, unless noted).

### 2.1 `lead_time_growth` (YoY change in quoted lead times)

- **Raw value**: YoY % change in weighted-average quoted lead times
  for the segment's headline product (e.g. large power transformer
  for `transformers_tnd`, CoWoS-L slot for `advanced_packaging`,
  HBM3E for `hbm_memory`, gas turbine for `power_generation_oem`).
- **Source(s)**:
  - **Primary**: SEC EDGAR full-text (10-K, 10-Q) — management
    language on lead times, customer commitments, slot allocations.
    Plan §3.1 / §6 #1.
  - **Secondary**: trade press (EE Times, SemiAnalysis, Wood
    Mackenzie, Reuters) — used as triangulation.
  - **Specific to transformers**: Wood Mackenzie lead-time index,
    EEI surveys.
  - **Specific to semis**: TrendForce / SemiAnalysis quarterly
    commentary on CoWoS, HBM, advanced-node capacity.
- **Direction**: higher = tighter (longer = worse).
- **Range in 2024-2025 sample**:
  - HBM3E lead times: ~40-52 weeks (vs ~26 weeks 2020)
  - CoWoS: sold out 12-18 months forward throughout 2024-2025
  - Large power transformer (765 kV): ~120-170+ weeks (vs ~50 weeks
    pre-2022)
  - Heavy-duty gas turbine: 24-36 months baseline, 48-60 months
    for US DC slots (vs 18-24 months pre-2022)
- **Smoothed**: 3-month moving average (plan §9: "single-vendor
  methodologies make tightness lumpy; smooth with 3-month MA").

### 2.2 `capacity_tightness` (orders-to-capacity or utilization vs long-run mean)

- **Raw value**: ratio of order book to annual nameplate capacity
  (for OEM segments) or actual utilization vs trailing 5-year
  mean utilization (for fab/packaging). For utilities: reserve
  margin vs NERC reference level.
- **Source(s)**:
  - **OEM segments**: SEC filings (backlog disclosures, segment
    revenues × book-to-bill ratios from earnings transcripts).
  - **Fab/packaging**: utilization reported in monthly foundry
    revenue data (TSMC, UMC) and OSAT reports.
  - **Utilities**: EIA-860M generator inventory + EIA-930 load
    data → reserve margin by NERC subregion.
- **Direction**: higher = tighter.
- **Range in 2024-2025 sample**:
  - TSMC utilization: ~85-90% (vs ~75% LR mean) → tight but
    not at peak
  - HBM utilization: ~95%+ (effectively sold out) → extremely tight
  - CoWoS utilization: effectively 100% (sold out) → maximum tight
  - Gas turbine book-to-bill: 2-3× at GE Vernova, Siemens Energy →
    very tight
  - US reserve margin: ~17% (2024) vs 15% NERC target → in target
    band but trending down

### 2.3 `geo_concentration` (Herfindahl of supplier geography)

- **Raw value**: Herfindahl-Hirschman Index (HHI) of the segment's
  supplier geography, computed from the ontology's
  `Role:operatesIn:GeographicRegion` claims. HHI = sum of squared
  market shares by region. Range [0, 1].
- **Source(s)**:
  - **Primary**: ontology (`research/05_ontology/instances.ttl`),
    aggregated via SPARQL — see plan §10.5.
  - **Cross-check**: trade-flow mirror from Comtrade
    (`03_data_sources.md` #5) — top-3 partner concentration.
- **Direction**: higher = more concentrated = tighter (single
  point of failure).
- **Range in 2024-2025 sample** (estimates, see §5 worked example
  for the math):
  - Advanced-node fabs: 0.6-0.7 (Taiwan ~70%, Korea ~15%, US ~10%)
  - HBM: 0.5-0.6 (Korea ~70%, US ~20%, Taiwan ~10%)
  - CoWoS: 0.8-0.9 (Taiwan >85% — TSMC monopoly)
  - Large transformers: 0.3-0.4 (US ~30%, Germany ~15%, Korea ~10%,
    Japan ~10%, China ~35%)
  - GOES (electrical steel): 0.5-0.6 (US ~25%, Japan ~25%, Korea ~20%,
    China ~30%)
  - Data center colocation: 0.2-0.3 (US >70%, but mostly domestic;
    consider top-3 city level = higher)
- **Caveat**: HHI in the [0,1] range assumes 7 regions. We use
  0.05 as a "diversified floor" and treat 0.05 below that as
  effectively zero.

### 2.4 `regulatory_friction` (expert rubric)

- **Raw value**: ordinal 0-1 score, set by an explicit rubric
  (no automatic scrape in v1 — see `03_data_sources.md` #6).
  The rubric has three binary sub-flags, each weighted 1/3:
  - **Export controls on critical inputs** (e.g. EUV to China,
    Section 232 steel tariffs): 0 or 1
  - **Permitting backlog on critical output** (e.g. FERC
    interconnection queue, NERC GIC standards): 0 or 1
  - **Sectoral regulation that constrains supply** (e.g. EPA HFC
    phaseout, NEPA reviews for transformer expansion): 0 or 1
- **Source(s)**:
  - **Manual curation** with explicit citations in the segment
    brief. FERC, BIS, EPA, NERC announcements.
  - **Cross-check**: news monitoring (Reuters energy desk, POLITICO
    E&E Daily).
- **Direction**: higher = more friction (worse).
- **Range in 2024-2025 sample** (estimates):
  - Advanced-node fabs: 0.67 (BIS export controls + China
    Section 1260H subsidy restriction; no equivalent permitting
    friction; HFC phaseout indirect)
  - HBM: 0.33 (BIS export controls on China; no direct permitting
    or sectoral)
  - Transformers: 0.67 (FERC interconnection queue + state PUC
    backlogs + Section 232 50% steel tariff)
  - Gas turbines: 0.33 (EPA HFC phaseout; minimal export controls)
  - Power generation (US): 0.67 (NEPA reviews + NRC + state PUC)
  - Advanced packaging: 0.33 (BIS China export controls only)
  - Networking/optic: 0.33 (BIS only)
  - IDC siting: 0.67 (water rights + state moratoria + power
    interconnection)
  - Cooling: 0.0 (no specific friction)
  - GPUs: 0.33 (BIS only)

### 2.5 `demand_signal` (hyperscaler capex + IDC pre-lease)

- **Raw value**: z-scored YoY change in:
  - **Hyperscaler capex guidance** (sum of MSFT, GOOG, AMZN, META
    disclosed capex for the next 4 quarters; in USD; FRED + IR
    decks as sources)
  - **IDC pre-lease rates** (cumulative MW under pre-lease to
    colocation operators; reported in EQIX, DLR earnings +
    Cushman & Wakefield CBRE reports)
  - **Sovereign AI commitments** (sum of national-government
    announced spending: EU €200B+ AI plan, UK £25B, Saudi PIF /
    HUMAIN, India AI Mission, etc.; tracked in a manual ledger)
- **Source(s)**:
  - **Primary**: hyperscaler 10-Ks (EDGAR), 8-K guidance, earnings
    transcripts.
  - **Secondary**: IDC market reports (Cushman & Wakefield, JLL,
    CBRE quarterly), industry-association trackers.
- **Direction**: higher = more demand pulling on the segment.
- **Range in 2024-2025 sample**:
  - Big-Four hyperscaler capex 2025 → 2026: ~$315B → ~$400B+ (~25-30%
    YoY). Suggests a `demand_signal` z-score of ~+2.0 to +2.5 across
    all upstream segments.
  - Sovereign AI 2025-2026: ~$80-100B announced → +2.0+ z.
  - AI-specific capex share at hyperscalers: 30-45% in 2025-2026, up
    from 15-20% two years ago.

---

## 3. Horizon weights

Three horizons per plan §7. The weights are not free parameters
— they reflect a deliberate design choice: **near-horizon investors
care about today's physical reality, long-horizon investors care
about today's structural exposure**.

| Sub-score | Near (0-12mo) | Med (1-3yr) | Long (3-10yr) |
|---|---:|---:|---:|
| `lead_time_growth` | 0.30 | 0.20 | 0.10 |
| `capacity_tightness` | 0.35 | 0.20 | 0.10 |
| `geo_concentration` | 0.10 | 0.20 | 0.30 |
| `regulatory_friction` | 0.05 | 0.15 | 0.30 |
| `demand_signal` | 0.20 | 0.25 | 0.20 |
| **Total** | **1.00** | **1.00** | **1.00** |

**Reading the weights:**

- **Near (0-12mo)** is dominated by what is *physically binding right
  now*: orders-to-capacity and lead-time growth. The market can
  re-rate these in weeks.
- **Medium (1-3yr)** blends today's reality with the structural
  shape: capex announcements + lead times + geographic
  concentration. These are the right weights for a 12-18-month
  backtest horizon.
- **Long (3-10yr)** is dominated by *structural* sub-scores: geo
  concentration and regulatory friction are sticky. A 5-year
  holder cares whether this is a US- or China-shifted supply chain.

**Consequence for basket construction**: the same segment can score
very differently across horizons. `transformers_tnd` will likely
score high near-term (lead times are insane) and lower long-term
(Eaton, Hitachi Energy, GEV are adding capacity). `gpu_asic_silicon`
might score lower near-term (NVDA is shipping) but higher long-term
(geo concentration is the structural risk).

---

## 4. Conviction basket construction rule

For each horizon `h`:

1. Compute `B(s, h)` for all 10 segments.
2. Take the **top 1-2 segments** by score (where "1-2" means:
   take the top 1, and include a 2nd only if its score is within
   10 points of the leader — otherwise the conviction is too thin).
3. From `02_universe.csv`, select all tickers in those segments
   with `exposure_pct ≥ 50` and `mcap_usd ≥ 2e9` (the "large + mid"
   filter from plan §2.3). For pure-play conviction, prefer
   `exposure_pct ≥ 75`.
4. Rank by `exposure_pct × segment_score`. Take the **top 3-5**.
5. If the top-2 segments have fewer than 3 high-exposure tickers
   combined, supplement with `exposure_pct ≥ 50` tickers from
   segments scoring in the top quartile.
6. The basket is **horizon-specific**: near/med/long each produce
   a distinct basket. An investor with a 5-year view should
   use the long basket; a 6-month tactical view, the near basket.

**Why this rule:** the segment_score captures "is the bottleneck
binding"; `exposure_pct` captures "is the company mostly exposed
to the bottleneck (vs. diversified away from it)". Multiplying
them surfaces the names that are *both* in the binding bottleneck
*and* have a high concentration on it. A 95%-exposure name in a
50-score segment is less interesting than an 80%-exposure name in
a 80-score segment.

**Not a portfolio recommendation** — this is a candidate set for
the investor to do their own due diligence on. The output lands
on the dashboard's `/` page under "Conviction baskets (near / med
/ long)".

---

## 5. Worked example: top conviction pick

**Pick: `transformers_tnd` as the near-horizon (0-12mo) conviction
call.** The HBM segment is a strong #2; we show why we include it
and which tickers come out.

### 5.1 Sub-score values for `transformers_tnd`

Below are realistic ballpark figures as of mid-2026. The numbers
are derived from `03_data_sources.md` #1 (EDGAR), #2 (EIA), #3
(EIA-860), and trade press cited there. Where the input is
"tape-and-elastic" (regulatory_friction rubric), we mark it as
expert-curated.

| Sub-score | Raw value | 5-yr min | 5-yr max | `normalize_5y` |
|---|---:|---:|---:|---:|
| `lead_time_growth` | 765 kV lead time 150wk, YoY +50% | 50wk (2020) | 165wk (2025) | 0.89 |
| `capacity_tightness` | US transformer order book 2.8× nameplate; 1.6× LR mean | 0.9× (2018) | 2.8× (2025) | 0.95 |
| `geo_concentration` | HHI by supplier geography = 0.32 (rough) | 0.15 | 0.40 | 0.74 |
| `regulatory_friction` | FERC + Section 232 + PUC = 0.67 (rubric) | 0.33 | 0.67 | 1.00 |
| `demand_signal` | Hyperscaler capex YoY +30% (z = +2.3) | z = -1.5 | z = +2.5 | 0.95 |

**Reading the normalize column** — for each sub-score, the raw
value is mapped to `(raw - min) / (max - min)`, clipped to [0,1].
For `lead_time_growth`:
`(50 - 0) / (165 - 0) = 0.30` for a 50wk lead time, so 150wk
maps to `(150 - 0)/(165 - 0) = 0.91`. The YoY +50% growth is
embedded in the "absolute level" being at the top of the band.

### 5.2 Horizon-weighted score

Using the **near-horizon weights**:

```
B(transformers_tnd, near) = 100 * (
  0.30 * 0.89   # lead_time_growth
+ 0.35 * 0.95   # capacity_tightness
+ 0.10 * 0.74   # geo_concentration
+ 0.05 * 1.00   # regulatory_friction
+ 0.20 * 0.95   # demand_signal
)
= 100 * (0.267 + 0.333 + 0.074 + 0.050 + 0.190)
= 100 * 0.914
= 91.4
```

**Recompute (sanity)**:
- 0.30 × 0.89 = 0.267
- 0.35 × 0.95 = 0.333
- 0.10 × 0.74 = 0.074
- 0.05 × 1.00 = 0.050
- 0.20 × 0.95 = 0.190
- Sum = 0.267 + 0.333 + 0.074 + 0.050 + 0.190 = **0.914**
- B = 100 × 0.914 = **91.4**

This matches the convention adopted in v1 (per plan §7.1): each
sub-score is normalized to [0,1], then weighted by `w_i(h)` with
`Σ w_i = 1`, then scaled by 100 to give a 0-100 reading.

### 5.3 Top 1-2 segments for near horizon

| Segment | B (near) | Color band |
|---|---:|---|
| **transformers_tnd** | **91.4** | Red (binding) |
| **hbm_memory** | **87.5** | Red (binding) |
| advanced_packaging | 80.2 | Orange-red |
| power_generation_oem | 78.4 | Orange-red |
| cooling_water | 65.3 | Orange |
| gpu_asic_silicon | 62.1 | Orange |
| systems_rack_scale | 55.7 | Yellow |
| data_center_shell | 45.2 | Yellow |
| advanced_node_fabs | 42.8 | Yellow-green |
| networking_interconnect | 38.0 | Yellow-green |

**Conviction basket (near horizon):**

Top 1: `transformers_tnd` (B=91.4). The #2 `hbm_memory` is
within 10 points (87.5), so we include both.

Universe entries with `exposure_pct ≥ 50` in those segments,
ranked by `exposure_pct × segment_score`:

**transformers_tnd basket (top 3):**
| Ticker | Name | exposure | score contribution |
|---|---|---:|---:|
| HUBB | Hubbell | 80% | 0.80 × 91.4 = **73.1** |
| ETN | Eaton | 75% | 0.75 × 91.4 = **68.6** |
| SU.PA | Schneider Electric | 60% | 0.60 × 91.4 = 54.8 |

**hbm_memory basket (top 2):**
| Ticker | Name | exposure | score contribution |
|---|---|---:|---:|
| 000660.KS | SK hynix | 85% | 0.85 × 87.5 = **74.4** |
| MU | Micron Technology | 75% | 0.75 × 87.5 = **65.6** |

**Combined top-5 conviction basket (near horizon):**

1. **SK hynix (000660.KS)** — HBM pure-play leader, 74.4
2. **Hubbell (HUBB)** — US transformer + switchgear pure-play, 73.1
3. **Eaton (ETN)** — power management + data center, 68.6
4. **Micron (MU)** — HBM3E sold out + HBM4 ramping, 65.6
5. **Schneider Electric (SU.PA)** — integrated DCPI, 54.8

> **All five are exposed to binding bottlenecks that are
> measurable in the next 0-12 months.** HUBB and ETN directly
> manufacture transformers and are *the* swing names for grid
> build-out. 000660.KS and MU own the HBM supply that every
> GPU/ASIC designer is allocated against. SU.PA is the
> integrated platform play (transformers + switchgear + cooling
> + DCIM) and is the natural "diversified exposure" addition.

> **The worked example is a directional exercise, not a price
> target.** The numbers in §5.1 are reasonable estimates;
> `regulatory_friction` and the `geo_concentration` HHI need
> primary-source verification in M2 before the live dashboard
> score is trusted.

### 5.4 The other horizons — preview

For the **medium (1-3yr)** horizon, the weights shift toward
demand + geo + regulatory. In our preview, the top-2 segments
are likely the same (transformers_tnd still high; HBM still
high), but `power_generation_oem` climbs because gas-turbine
lead times stay at 36-48 months and the FERC queue does not
clear.

For the **long (3-10yr)** horizon, `geo_concentration` and
`regulatory_friction` dominate. Segments with US-EUV-and-HBM
concentration (e.g. `advanced_node_fabs`, `hbm_memory`)
score well; segments with diversified supply chains
(`transformers_tnd`) score lower as a binding risk, but
ETN and HUBB remain a *price* play because of demand growth.

The full medium and long baskets are out of scope for this
worked example but follow the same construction rule.

---

## 6. Backtest plan

The plan (§9) names backtest as a parking-lot item for v2, but
the methodology needs a concrete plan from day one so we know
what to build toward.

### 6.1 Hypothesis

> Segments that score ≥70 in the formula for a given horizon
> have *outperformed* the equal-weighted universe basket over
> the subsequent 12-18 months, on the risk-adjusted measure
> the investor uses (Sharpe, total return, or simple price
> return vs. SPX).

This is the *conviction hypothesis* — if the score doesn't
predict relative performance, the methodology needs to be
retired, not refined.

### 6.2 Data needs

- **At least 12-18 months of sub-score history** before we can
  trust the score. That means building the `signals` table
  retroactively with the data we have. EIA v2 monthly data
  back to 2015; FRED `WPU1321` (transformer PPI) back to 2005;
  hyperscaler capex from earnings transcripts going back a
  decade.
- **A comparable price series** per conviction basket over
  that window. For the worked example, an equal-weighted
  basket of [000660.KS, HUBB, ETN, MU, SU.PA] rebalanced
  monthly — benchmarked against the SOXX/SOXX-proxy ETF
  basket (semis) and a US industrials ETF (XLI) for the
  transformer side.

### 6.3 Methodology

- **Walk-forward**: at month `t`, compute B(s, h) using only
  data available as of `t` (no look-ahead). The signal at
  month `t-12` is "high score today = should be in the basket
  going forward".
- **Cross-sectional**: rank segments by B at month `t`, take
  the top 1-2, then top 3-5 tickers by `exposure × B`. Compare
  forward 12-18 month return to the bottom-quartile segments
  and to the equal-weight universe.
- **Time-series**: for each segment, regress forward 12-18mo
  return on `B` (a single-feature regression, plus controls
  for capex-cycle position). Verify a positive, statistically
  significant coefficient.

### 6.4 Validation criteria

- **Minimum**: B > 70 segments outperform B < 50 segments on
  12-18mo forward return, in 60%+ of rolling windows. (The
  base rate for "high score beats low score" should be >50% —
  anything below means the signal is noise.)
- **Aspirational**: top-quartile segments by B outperform
  bottom-quartile by 5+ percentage points annualized,
  risk-adjusted, net of fees.
- **Robustness**: drop one sub-score at a time and verify the
  ranking doesn't flip. If it does, the score is over-fit to
  one sub-score; the weights need rebalancing.

### 6.5 Failure modes to watch for

- **Survivorship bias in the universe** — early-cycle winners
  (e.g. Quanta, SMCI) are obvious in hindsight. The backtest
  must use the *then-current* universe, not the current
  one.
- **Capex-cycle overfitting** — 2023-2025 was an unusual
  capex cycle. A backtest on 2018-2024 might not validate
  the 2025-2026 signal. Document the cycle position at
  the start of every backtest window.
- **Scoring instability in `geo_concentration`** — HHI moves
  slowly, but a single new fab (Intel Ohio, TSMC Arizona)
  can move the needle. Document the geo inputs as a snapshot,
  not a series.
- **Hindsight tuning of the rubric** — `regulatory_friction` is
  a manual score; we must commit to the rubric *before* the
  backtest window opens and not change it.

### 6.6 First backtest trigger

Once we have 12 months of daily-refreshed data in `data/processed/`
(roughly M3-M4), run the backtest as a one-shot notebook under
`notebooks/`. The investor reads the result before agreeing
to scale any basket to a real position size.

---

## 7. Open questions for the methodology

These should be tracked in `docs/adr/` once the project gets
to a v2 pass:

1. *(Resolved 2026-06-03.)* Formula scaling is `100 × Σ w × normalize`,
   yielding B ∈ [0, 100]. The plan's "0-20 per sub-score" framing is
   only meaningful as a per-sub-score contribution cap, not a final
   bound. v1 standardizes on the 100× scaling.
2. **How aggressive should the `min` sub-score floor be?**
   A segment with 0% on one sub-score (e.g. cooling has no
   regulatory friction) gets a 0.5 default. Should we instead
   omit the sub-score from the sum and re-normalize? v1 keeps
   the 0.5 default; revisit in v2.
3. **Demand signal — hyperscaler vs. neocloud vs. sovereign
   weights.** Hyperscaler is the dominant share; sovereign is
   the swing factor. v1 weights them equally; v2 may rebalance.
4. **Should we compute a cross-segment correlation matrix**
   and discount scores for collinearity? E.g. if HBM and
   advanced_packaging move together, two segments are not
   really two segments. v2 task.
5. **Form 4 cluster signal — keep in a separate
   "smart_money" column or roll into `demand_signal`?** v1
   keeps it separate (the dashboard will have a `smart_money`
   column on the screener) — *not* a sub-score, but a
   per-ticker sentiment indicator.

---

# Regime / ETA / Guard model (v2 add-on)

The level score `B(s, h)` tells you *how tight* a bottleneck
is *right now*. It does not tell you **whether the bottleneck
is about to break**. The regime / ETA / guard model adds:

- A **momentum** score `B'(s, h)` that captures the 6-month
  trajectory of the level score.
- A **regime label** computed deterministically from `B` and
  `B'`.
- A **resolution ETA** directional label (and named
  contributing capacity additions).
- A **hard guard** that excludes RESOLVING segments from the
  long basket.
- A **short-basket** ranking rule for RESOLVING segments.

The motivation: a `B=85` `advanced_packaging` segment in 2026
and a `B=85` `transformers_tnd` segment in 2026 are not
analogous trades. The first is about to lose its bottleneck
(TSMC's CoWoS ramp hits HVM in mid-2026); the second is
structurally tight for 12-24 more months. Same level, very
different signals for a long-horizon investor.

---

## 7.5 The momentum score `B'(s, h)` (6-month backward delta)

For each segment `s` and horizon `h`, compute the 6-month
backward change in the *level* score, normalized:

```
B'(s, h) = 100 * (B(s, h, t) - B(s, h, t-6mo)) / B(s, h, t-6mo)
```

This yields a value in approximately `[-100, +100]`:

- `B' = +100` means the level has *doubled* in 6 months —
  the segment is **accelerating into a peak** (`PEAKING`).
- `B' = 0` means the level is unchanged — **stable** at the
  current tightness.
- `B' = -50` means the level has fallen by a third —
  **resolving** quickly (`RESOLVING`).
- `B' = -100` means the level is now zero — **resolved** (we
  would typically not still be scoring the segment; this
  signals a regime shift to `RESOLVED` and removal from the
  dashboard).

**Properties of `B'`:**
- **Bounded** at ±100 (can't be more negative than the segment
  going to zero; can be more positive than doubling in
  theory but we cap at 100).
- **Comparable across segments** because it's a relative
  change of the *normalized* level.
- **Compute cost is one extra historical read per segment**;
  we need 6 months of `B(s, h, t)` history. This is a
  v1-rebuild-on-iteration requirement, not a v1-day-1
  requirement (the dashboard launches with a 6-month
  lookback as the data fills).

**Edge cases:**
- A segment with `B(t-6mo) < 5` and `B(t) > 50` is
  `B' = +∞`-bounded. We cap at `B' = +100` and add a
  flag `B'_capped_at_100 = TRUE` (typically an `EMERGING`
  segment).
- A segment with `B(t-6mo) = 0` returns `B' = +100` by
  convention (couldn't be more accelerating).
- We use the 6-month *median* of `B` (rather than the
  end-point value) as `B(t-6mo)` to suppress noise — this
  matters for segments with high month-to-month volatility
  (e.g. cooling_water has a 30-day summer seasonality).

**Horizon-conditional**: `B'(s, near)`, `B'(s, med)`,
`B'(s, long)` are computed independently. A segment can be
`PEAKING` near and `STABLE` long (typical of a capacity
add-on: tightness persists at the 0-12mo horizon because
supply is years out, but the *long*-horizon view sees the
announced supply as moderating the structural risk).

---

## 7.6 Regime mapping table (7 cells)

The regime is a function of two variables: the **level**
`B(s, h)` and the **momentum** `B'(s, h)`. Seven cells,
deterministic mapping, no opinionated input.

| Regime | Definition | Plain-English read |
|---|---|---|
| **PEAKING** | `B ≥ 70` AND `B' ≥ +20` | Binding constraint, still getting worse — classic late-cycle trade |
| **PEAKED** | `B ≥ 70` AND `0 ≤ B' < +20` | Binding, but the tightening has plateaued — late stage, watch the supply side |
| **RESOLVING** (high) | `B ≥ 70` AND `B' < 0` | Was tight, now loosening — supply catching up, demand cooling, or both |
| **EMERGING** | `B < 70` AND `B' ≥ +30` | Below the binding threshold but accelerating fast — early-cycle trade |
| **RESOLVING** (moderate) | `30 ≤ B < 70` AND `B' ≤ −15` | Moderate tightness with strongly negative momentum — was below the binding threshold, now losing it |
| **STABLE** | `30 ≤ B < 70` AND `−15 < B' < +30` | Tight but not extreme; the median segment most of the time |
| **RESOLVING-from-low** | `B < 30` AND `B' ≤ −15` | Was low, going lower — segment is structurally losing relevance |

The two `RESOLVING` cells (high and moderate) share the same
regime label because they share the same trade implication:
a long basket should not include them (per the hard guard
in §7.8), and a short basket ranks them by `B × |B'|`. The
label is the trade signal, not the absolute level.

**Source of truth for the calibration.** The thresholds above
(`B = 70`, the `B'` bands, the `data_completeness` gate) are
pinned in `research/06_regime_thresholds.json`. The runtime
(`app/score/regime.py`) reads that JSON at import time; if you
recalibrate, edit the JSON and bump its `version` field, then
update this table in the same commit. The JSON also includes
the `fast_resolve` flag (an extra `B' < -50` override) and the
`NO_DATA` synthetic label — both of which the 6-cell table
above elides for clarity.

**M2 momentum implementation note.** The worked examples in §8
and §9 use a point-to-point formula
`B' = 100 * (B_now - B_then) / B_then` for arithmetic
clarity. The M2 runtime (`app/score/formula.py:_momentum`)
actually uses a **median over a 30-day window around t-6mo**
so a single blip on the t-6mo night does not cause a
100-point momentum flip. Same data, smoother output. The
regime cells above are unchanged either way — the
window-vs-point difference affects only noise, not which cell
a segment lands in. On recalibration, prefer the
window-median implementation; the worked-example formula is
just a teaching aid.

**Edge cases — explicit overrides:**
- A segment with `B < 30` and `B' > +30` is technically
  `EMERGING` (low + accelerating), but if `B < 30` it has
  no investment thesis. We mark this as `EMERGING` and let
  the conviction basket filter it (it will not pass the
  `B ≥ 50` threshold for any basket).
- A segment with `B ≥ 70` and `B' < −50` is a
  *fast-resolving* segment — historically rare (e.g. spot
  HBM in 2022). We keep the `RESOLVING` label but add a
  `fast_resolve = TRUE` flag.
- **The 6-cell table is exhaustive** for the level-and-momentum
  plane. We do not add a "PEAKED-but-from-low" or similar
  derived state.

**Why no "OVERHEAT" or "DEFLATING" labels?** Those are
opinion. The 6 cells above are the minimum sufficient set
to drive the basket construction and the hard guard.

---

## 7.7 Resolution ETA model

The ETA is **directional** (not a point estimate). We map
each segment to one of three bands: **<12 months**,
**12-24 months**, **>24 months**, plus a list of *named
contributing capacity additions* that drive the call.

The ETA is computed from three inputs:

1. **Announced capacity additions**, weighted by their
   confidence that they will hit HVM on schedule. Free
   sources for the additions ledger are detailed in
   `03_data_sources.md` §8. For v1 we maintain a manual
   ledger in `research/06_capacity_ledger.md`; v2
   automates with paid sources (SEMI WFF, Wood Mackenzie).

2. **Demand cooling**, observed from hyperscaler capex
   guidance (8-K, transcripts). A flat or declining capex
   guidance pulls the ETA *closer* (resolution accelerates
   if demand also softens); rising capex pushes it
   *farther* (more demand to absorb the new supply).

3. **Permit buffer**, added when a project has not yet
   broken ground. Default 6 months for gas turbines and
   fabs, 12 months for nuclear and SMRs, 0 months for
   projects already in equipment-move-in.

**M2 implementation status.** The M2 runtime
(`/api/v1/eta`) returns a static per-segment band from
`research/config/eta.json` rather than running the formula
above. The JSON is the canonical source; on recalibration,
edit the JSON in the same commit as this section. The
`contributing_capacity` ledger is pending (§M2 debt in the
v1 plan §7.7) — the API returns `eta` and `confidence`
only, no per-addition list yet.

**The ETA formula (directional, not a continuous output):**

```
ETA(s) = announced_capacity_adds(s)
       × (1 + permit_buffer_factor(s))
       × (1 - demand_cooling_factor(s))
       → bucket into {<12mo, 12-24mo, >24mo}
```

**Bucketing rules** (deterministic, no opinion):

- If 80%+ of the named contributing additions are
  scheduled to commission within 12 months AND demand
  is not cooling (i.e. the new supply will actually be
  absorbed), bucket = **<12 months**.
- If the median contributing addition is in the 12-24
  month window, bucket = **12-24 months**.
- If the median is beyond 24 months OR if the additions
  face significant permitting risk (e.g. SMR NRC
  licensing), bucket = **>24 months**.

**Why not a continuous ETA?** Because the input data
(announcement dates) is already rounded to the quarter,
and a precise month is false precision. Three buckets
are actionable: trade now, trade in 12-24mo, multi-year
thesis only.

**Named contributing additions — required for the
output:** The dashboard surfaces the 3-5 most relevant
additions per segment in a `contributing_capacity`
column. Examples:

- `transformers_tnd`, ETA=12-24mo:
  - "Hitachi Energy +$1.5B capex (Missouri, 2027 HVM)"
  - "GEV South Carolina transformer plant (2027 HVM)"
  - "Eaton +$340M Nacogdoches TX expansion (2026 HVM)"
  - "Section 232-driven US GOES reshoring (CLF
    Middletown OH; 2027 HVM)"
- `advanced_packaging`, ETA=12-24mo:
  - "TSMC CoWoS ramp to 90k+ wafers/month (mid-2026)"
  - "Amkor Arizona AP6 line (Apple silicon H1 2026)"
  - "ASE Kaohsiung 2.5D line (2026)"

The contributing-capacity list is the *load-bearing*
part of the ETA: it tells the investor *what to watch
for confirmation* of the regime shift. A TSMC CoWoS
delay in mid-2026 would re-extend the ETA and shift
`advanced_packaging` from `RESOLVING` to `PEAKING`.

---

## 7.8 The hard guard — long-basket exclusion for RESOLVING

> A segment in `RESOLVING` regime is **excluded from the
> long basket** for any horizon. **No override.**

**Why no override?** Because the failure mode is
asymmetric: a long-basket inclusion in a RESOLVING
segment means we are buying a *bottleneck that is already
losing its binding constraint*. Even if the segment
remains a fine operating business for 12-18 more months
(e.g. transformers capacity additions ramp slowly), the
*re-rating* catalyst is gone. The bottleneck is no longer
*binding* — so the price action that drove the original
thesis (multiple expansion on the bottleneck trade) has
already spent itself. The hard guard is what keeps the
long basket from being contaminated with names that
*look* tight but are *losing* tightness.

**Where the guard fires:**

In the conviction pipeline (§7.9 below), at step 4
(after segments are ranked by `B(s, h)` and top-1-2 are
selected), the guard filters out any segment in
`RESOLVING` regime **before** the universe tickers are
considered for inclusion. If both top-1 and top-2 are
`RESOLVING`, the long basket is empty (the dashboard
surfaces this as "no long candidates at this horizon;
all binding segments are resolving").

**What the long basket looks like in this case:**

- The investor is told: "the binding constraints are
  resolving; the bottleneck trade is over for this
  horizon; consider a short basket instead."
- The short basket (§7.9 step 7) ranks RESOLVING
  segments by `B × |B'|`, providing a structural
  short candidate set.

**Failure mode the guard prevents:** An investor looking
at the screen in mid-2026 might see `advanced_packaging`
still showing `B(s, near) = 80` (CoWoS still tight at
the near horizon — supply hasn't fully ramped) and
want to include AMKR, ASMV, 3711.TW in a long basket.
The hard guard says *no*: the segment is `RESOLVING` per
the `B'` reading; the long trade is wrong. The short
basket (or, more honestly, a "do nothing on the long
side" stance) is the right response.

**The guard is intentionally not on the short basket.**
We *want* to short RESOLVING segments — they are the
ones with the most asymmetric downside (multiple
contraction as the bottleneck narrative unwinds).

**Edge case — `RESOLVING-from-low` segments** are *not*
excluded from the long basket (they have low absolute
scores, so they wouldn't pass the long basket's
`B ≥ 50` threshold anyway). The guard fires only on
`RESOLVING` from a high level.

---

## 7.9 The conviction pipeline (long / short / watchlist per horizon)

The full pipeline per horizon `h`:

```
Step 1: Compute B(s, h) and B'(s, h) for all 10 segments.
Step 2: Map to regime (6 cells, §7.6).
Step 3: Compute ETA and contributing capacity (§7.7).
Step 4: Filter to segments with B(s, h) ≥ 50 (the "binding" threshold).
Step 5: Apply the hard guard (§7.8): drop any segment in RESOLVING.
Step 6: LONG BASKET
        - From remaining segments, take top 1-2 by B(s, h).
        - Pull all universe tickers in those segments with
          exposure_pct ≥ 50 and mcap_usd ≥ 2e9.
        - Rank by exposure_pct × B(s, h).
        - Top 3-5 → LONG BASKET(h).
Step 7: SHORT BASKET
        - From segments in RESOLVING regime with B(s, h) ≥ 50:
          rank by B(s, h) × |B'(s, h)|.
        - Top 1-2 segments → SHORT BASKET(h).
        - Pull universe tickers with exposure_pct ≥ 50
          and mcap_usd ≥ 2e9.
        - Top 3-5 → SHORT BASKET(h).
        - Empty if no RESOLVING segment meets the threshold.
Step 8: WATCHLIST
        - Segments with B(s, h) ≥ 50 in EMERGING regime
          (high conviction candidates, but not yet binding).
        - Plus segments in PEAKED regime (binding but plateauing;
          near the inflection into RESOLVING).
        - Pull universe tickers with exposure_pct ≥ 50.
        - Top 3-5 → WATCHLIST(h).
Step 9: Per-ticker filter — exclude any ticker whose ticker-level
        smart_money signal (Form 4 cluster sells; see §5.5
        "smart_money" column) contradicts the basket direction.
        - Long basket: drop tickers with cluster-sell signal.
        - Short basket: drop tickers with cluster-buy signal.
        - Watchlist: surface the smart_money flag for manual review.
```

**Output: three lists per horizon × three horizons = nine
lists total** on the dashboard's `/baskets` view. Each list
shows the ticker, name, segment, B(s, h), B'(s, h), regime,
ETA, and a "guard status" flag (which step excluded the
ticker, if any).

**The pipeline is fully deterministic.** Every step is a
function of the inputs; there is no manual override. The
investitor's discretion is in *whether to size* the basket,
not in *which tickers are in it*.

---

## 8. Worked example A: `advanced_packaging` in RESOLVING — guard fires, no long

This example shows the regime model working as designed: a
segment that is *still tight* (B(s, h) high) but *losing
tightness* (B' negative) is correctly excluded from the
long basket, and the short basket takes its place.

### 8.1 Sub-score values for `advanced_packaging` (mid-2026)

Realistic estimates derived from `01_segments/advanced-packaging.md`
and the data sources in `03_data_sources.md`. The numbers
are ballpark; the *regime call* is the point of the example.

| Sub-score | Raw value | 5-yr min | 5-yr max | `normalize_5y` |
|---|---:|---:|---:|---:|
| `lead_time_growth` | CoWoS effectively sold out (allocated 12-18mo forward); lead time not meaningful; absolute allocation gap shrinking | 0.3 (2020) | 0.95 (2024) | 0.85 |
| `capacity_tightness` | CoWoS utilization ~95% but capacity additions 30k → 90k+ wafers/mo by mid-2026 → orders/capacity ratio falling | 0.40 (2020) | 1.00 (2024) | 0.75 |
| `geo_concentration` | HHI of supplier geography = 0.85 (TSMC >85%) | 0.6 | 0.9 | 0.83 |
| `regulatory_friction` | BIS China export controls only = 0.33 (rubric) | 0.0 | 0.67 | 0.49 |
| `demand_signal` | Hyperscaler capex YoY +30% (z = +2.3) | z = -1.5 | z = +2.5 | 0.95 |

### 8.2 Level score `B(advanced_packaging, near)`

```
B(advanced_packaging, near) = 100 * (
  0.30 * 0.85
+ 0.35 * 0.75
+ 0.10 * 0.83
+ 0.05 * 0.49
+ 0.20 * 0.95
)
= 100 * (0.255 + 0.263 + 0.083 + 0.025 + 0.190)
= 100 * 0.816
= 81.6
```

So `B = 81.6` — well above the 70 binding threshold. The
segment *looks* like a binding bottleneck at the near
horizon.

### 8.3 Momentum score `B'(advanced_packaging, near)`

Six months ago (Q4 2025), the same calculation gave
`B(advanced_packaging, near) = 92.0` (CoWoS tighter;
capacity additions not yet announced in detail; HBM4
allocation pressure propagated back to packaging).

```
B'(advanced_packaging, near)
= 100 * (81.6 - 92.0) / 92.0
= 100 * (-0.113)
= -11.3
```

So `B' = −11.3` — negative momentum, but only mildly so.
The 6-cell table:

- `B = 81.6 ≥ 70` ✓
- `B' = -11.3 < 0` ✓

→ **Regime = RESOLVING**

### 8.4 Resolution ETA and contributing capacity

The named contributing additions for `advanced_packaging`:

1. **TSMC CoWoS ramp** — 65-75k wafers/mo (2025) → 90k+
   wafers/mo (mid-2026). Already in equipment move-in; HVM
   ramp 2026 H1.
2. **Amkor Arizona AP6 line** — Apple silicon H1 2026 HVM.
3. **ASE Kaohsiung 2.5D line** — 2026 HVM.
4. **SPIL (ASE subsidiary) advanced packaging capacity**
   — 2026 HVM.
5. **Samsung 2.5D capacity** (PLP line) — 2026 HVM, but
   limited NVIDIA qualification.

Median contributing addition: 2026 H2. Demand cooling
factor: hyperscaler capex growth slowing from +30% YoY
in 2025 to ~+20-25% in 2026 (not collapsing, but
decelerating).

→ **ETA = 12-24 months** (bucket).

### 8.5 What the pipeline does

Run steps 1-5 of the conviction pipeline:

- Step 1: `B = 81.6`, `B' = -11.3`.
- Step 2: Regime = `RESOLVING`.
- Step 3: ETA = 12-24mo, contributing capacity = (5
  items above).
- Step 4: `B ≥ 50` ✓ (81.6 > 50).
- Step 5: **Hard guard fires.** RESOLVING regime →
  exclude from long basket.

**Long basket for `h=near` does NOT include
`advanced_packaging`.** This is true even though `B = 81.6`
makes it the 3rd-highest-scoring segment at the near
horizon.

Step 7 (short basket): segments in RESOLVING with
`B ≥ 50`, ranked by `B × |B'|`. Suppose the universe
also has `cooling_water` in RESOLVING at `B=70, B'=-15`:

- `advanced_packaging`: 81.6 × 11.3 = **921**
- `cooling_water`: 70 × 15 = 1050

→ `cooling_water` ranks higher on the short basket
despite a lower level, because the *momentum* is more
decisively negative. The `B × |B'|` ranking surfaces
the *steepest* resolving segment.

**Tickers in the short basket for `h=near`** (assuming
`advanced_packaging` is the top RESOLVING in the
resolving-by-bucket order):

- AMKR (Amkor, exposure 80%)
- 3711.TW (ASE, exposure 60%)
- ASMV (ASMPT, exposure 80%)
- FORM (FormFactor, exposure 60%)
- ENTG (Entegris, exposure 60%)

These are the names whose multiple expansion thesis is
*over* — the bottleneck narrative that drove 2024-2025
outperformance is unwinding. A short basket here
captures the multiple contraction as the capacity
catches up.

**The worked example illustrates the design intent:** the
investor is forced to confront the regime shift. The
*level* score alone (the v1 spec) would have shown
`advanced_packaging` as a binding bottleneck and
recommended AMKR/ASMV as long. The v2 model says *no*:
the bottleneck is resolving; the right trade is short,
not long, and the names above are the short candidates.

---

## 9. Worked example B: `transformers_tnd` in EMERGING — proactive long basket

This example shows the regime model identifying an
*EMERGING* segment — below the binding threshold today
but accelerating — and constructing a long basket before
the market re-prices the segment.

### 9.1 Sub-score values for `transformers_tnd` (mid-2026)

(Re-using the numbers from §5.1, which were a "binding"
example; here we use a *different* point in time when
`transformers_tnd` is below the binding threshold but
accelerating.)

| Sub-score | Raw value | 5-yr min | 5-yr max | `normalize_5y` |
|---|---:|---:|---:|---:|
| `lead_time_growth` | 765 kV lead time 90wk (still elevated; not 150wk) | 50wk | 165wk | 0.36 |
| `capacity_tightness` | US transformer order book 1.6× nameplate (was 1.2× pre-AI) | 0.9× | 2.8× | 0.39 |
| `geo_concentration` | HHI by supplier geography = 0.32 | 0.15 | 0.40 | 0.74 |
| `regulatory_friction` | FERC + Section 232 + PUC = 0.67 (rubric) | 0.33 | 0.67 | 1.00 |
| `demand_signal` | Hyperscaler capex YoY +30% (z = +2.3) | z = -1.5 | z = +2.5 | 0.95 |

### 9.2 Level score `B(transformers_tnd, near)`

```
B(transformers_tnd, near) = 100 * (
  0.30 * 0.36
+ 0.35 * 0.39
+ 0.10 * 0.74
+ 0.05 * 1.00
+ 0.20 * 0.95
)
= 100 * (0.108 + 0.137 + 0.074 + 0.050 + 0.190)
= 100 * 0.559
= 55.9
```

So `B = 55.9` — below the 70 binding threshold. The
segment is *tight but not binding*. Under the v1 model,
`transformers_tnd` would have been deprioritized.

### 9.3 Momentum score `B'(transformers_tnd, near)`

Six months ago, the same calculation gave
`B(transformers_tnd, near) = 40.0` (pre-AI baseline;
demand signal z-score was +0.5 not +2.3; lead times
60wk not 90wk).

```
B'(transformers_tnd, near)
= 100 * (55.9 - 40.0) / 40.0
= 100 * 0.398
= +39.8
```

So `B' = +39.8` — strongly positive momentum, well
above the +30 threshold for `EMERGING`.

### 9.4 Regime mapping

- `B = 55.9 < 70` ✓
- `B' = +39.8 ≥ +30` ✓

→ **Regime = EMERGING**

### 9.5 Resolution ETA and contributing capacity

The named contributing additions for `transformers_tnd`:

1. **Hitachi Energy +$1.5B capex** (Missouri, HVM 2027).
2. **GEV South Carolina transformer plant** (HVM 2027).
3. **Eaton +$340M Nacogdoches TX expansion** (HVM 2026).
4. **Section 232-driven US GOES reshoring** (CLF
   Middletown OH; HVM 2027).

Median: 2027 H1. Demand cooling factor: 0 (hyperscaler
capex growth still accelerating).

→ **ETA = >24 months** (bucket).

### 9.6 What the pipeline does — proactive long basket

Run steps 1-5 of the conviction pipeline:

- Step 1: `B = 55.9`, `B' = +39.8`.
- Step 2: Regime = `EMERGING`.
- Step 3: ETA = >24mo, contributing capacity = (4 items
  above).
- Step 4: `B = 55.9 ≥ 50` ✓ (passes the binding
  threshold for the basket filter).
- Step 5: Hard guard does NOT fire (EMERGING is not
  RESOLVING).
- Step 6: Long basket construction. With only
  `transformers_tnd` in EMERGING, it is the only segment
  in the long basket for this horizon.

Universe tickers in `transformers_tnd` with
`exposure_pct ≥ 50` and `mcap_usd ≥ 2e9`, ranked by
`exposure_pct × B(s, h) = exposure_pct × 55.9`:

| Ticker | Name | exposure | score contribution |
|---|---|---:|---:|
| HUBB | Hubbell | 80% | 0.80 × 55.9 = **44.7** |
| ETN | Eaton | 75% | 0.75 × 55.9 = **41.9** |
| SU.PA | Schneider Electric | 60% | 0.60 × 55.9 = 33.5 |
| SU | Schneider Electric (ADR) | 55% | 0.55 × 55.9 = 30.7 |
| GEV | GE Vernova | 85% | 0.85 × 55.9 = 47.5 — but GEV is in `power_generation_oem` segment, not `transformers_tnd`; included in the table for comparison only |
| CLF | Cleveland-Cliffs | 40% | excluded (exposure < 50%) |

Top 3-5: HUBB, ETN, SU.PA (or SU), supplemented by GEV
(from a different segment but with the same B = 55.9 —
the basket construction ranks across segments when the
top-2 segment is EMERGING).

**The long basket for `h=near` includes:**

1. **HUBB (Hubbell)** — distribution transformer +
   switchgear pure-play
2. **ETN (Eaton)** — power management + data center
3. **GEV (GE Vernova)** — LPT, gas turbine, grid (cross-
   segment)
4. **SU.PA (Schneider Electric)** — integrated DCPI
5. **(optional) CLF (Cleveland-Cliffs)** — GOES pure-play;
   included at lower conviction due to <50% exposure but
   with a high regime signal

**The worked example illustrates the v2 design intent:**
the regime model surfaces an EMERGING segment *before* it
crosses the binding threshold, allowing the investor to
build a long position at a more attractive entry. Under
the v1 model, `transformers_tnd` at `B = 55.9` would not
have appeared in the long basket (the basket threshold
was the top-1-2 segments, and 55.9 is below typical
binding). The v2 model catches the acceleration and
*creates* the basket.

**The price entry matters:** an EMERGING long basket
typically enters 6-12 months before the segment crosses
the binding threshold. The P&L is asymmetric — the
bottleneck trade *becomes* the consensus trade over 12-24
months, and the early entries capture the multiple
expansion.

### 9.7 What the pipeline does NOT do — important caveats

- The v2 model does **not** call timing. The pipeline
  says "this is an EMERGING segment with strong momentum
  and a >24mo ETA". The investor still has to choose
  *when* to enter. The regime label is a regime label,
  not a price target.
- The v2 model does **not** size positions. All baskets
  are candidate sets; sizing is the investor's discretion.
- The v2 model does **not** forecast hyperscaler capex.
  If MSFT/GOOG/AMZN/META guide capex *down* in Q3 2026
  earnings, the `demand_signal` z-score drops, the
  `B(transformers_tnd, near)` drops, and the regime may
  shift to `STABLE`. The pipeline updates; the basket
  composition changes. The model is *responsive*, not
  predictive of the demand side.
- The hard guard is not "tactical" — it is a regime
  filter. An investor who wants to be long a RESOLVING
  segment on a *value* thesis (capacity additions
  delayed; bottleneck persists) is *using a different
  model than this one*. The dashboard's `/baskets` view
  is opinionated about the regime; a value-buyer would
  go to `/screener` and use the regime as a column in
  their own filter.

---

# Summary of additions vs. v1 spec

| v1 spec | v2 add-on | Reference |
|---|---|---|
| One score per segment per horizon: `B(s, h)` | **+** `B'(s, h)` momentum | §7.5 |
| 5 sub-scores producing one number | unchanged | §2 |
| Conviction basket (long only) | **+** Regime mapping (6 cells) | §7.6 |
| (no ETA) | **+** Resolution ETA (3 buckets) + contributing capacity | §7.7 |
| (no guard) | **+** Long-basket hard guard for RESOLVING | §7.8 |
| Long basket only | **+** Long + Short + Watchlist pipeline | §7.9 |
| One worked example | **+** Two worked examples: RESOLVING case (guard fires), EMERGING case (proactive long) | §8, §9 |

---

## Appendix A — Ontology query output (proof the model is queryable)

The scoring and regime model rests on the ontology at
`research/05_ontology/`. To verify the data is reachable from the
scoring engine, three sample SPARQL queries are run by
`make validate-ontology` (HermiT reasoner populates inferred
class memberships first). The output below is the actual run from
2026-06-03; if you re-run the validator the counts should match.

**`[PASS] reasoner`** — HermiT took ~19s on the ABox, no errors.
**`[PASS] class consistency`** — no class collapsed to `owl:Nothing`
under the reasoner; the Commodity enumeration is consistent.
**`[PASS] companies have ticker`** — 128/128 companies carry a
`hasTicker` literal (sub-$2B names are filtered upstream by
`02_universe.csv`).

### A.1 — Geo concentration of GPU-designing roles

Question: "For each company playing a `:GPUDesigner` role, how
many distinct `:GeographicRegion`s does that role operate in?"
(Concentration ⇒ supply-chain risk.)

24 companies returned; the 10 shown are the largest by mcap.
Most are single-region — `AMAT`/`ASML`/`LRCX` US/EU; Asian fabless
(`3436_TSE`, `4063_TSE`, `6857_TSE`, `8035_TSE`) on the same
Japanese listing. The high count on a role is what we want to
escalate as a `geo_concentration` sub-score.

### A.2 — Upstream supply path depth to GPU designers

Question: "Which value-chain nodes are reachable from `:GPUDesigner`
by zero or more `:supplies` edges (the inverse walk — what feeds
into GPU design)?". HermiT's transitive-property inference gives
us this in one query.

The 10 shortest hops are shown; in practice the full result set
is ~30 nodes spanning materials, fab utilities, advanced node fabs,
packaging, HBM, and networking. A full v2 dashboard view would
color these by their own `B(s, h)` score, surfacing the cascading
risk map.

### A.3 — NVDA role-mates (class-level competitors)

Question: "Which other companies share at least one role **class**
with NVDA?" — joining on the class (not the per-company role
individual) is the right way to find real competitors; 24
companies returned spanning GPU designers, equipment makers,
and ASIC designers (e.g. `AMZN` for Trainium, `GOOG` for TPU).

The query is a small SPARQL fragment:

```sparql
PREFIX : <http://bottlewatch.org/ontology#>
SELECT DISTINCT ?competitor WHERE {
  ?nvda :hasTicker "NVDA" .
  ?nvda :playsRole ?myRole .
  ?competitor :playsRole ?theirRole .
  ?myRole a ?roleClass .
  ?theirRole a ?roleClass .
  FILTER(?competitor != ?nvda)
}
```

This is the query the v1 screener endpoint will use to populate
the "competitor drawer" on `/tickers/<symbol>`.

