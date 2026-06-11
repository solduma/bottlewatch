// Tooltip / help text for the B(s, h) score column on the
// scoreboard. The same text is also rendered on the segment
// detail page. Mirrors the methodology §1 (formula) and §7.6
// (regime table — B >= 70 is the binding threshold per
// research/06_regime_thresholds.json).

export const SCORE_HELP = `B(s, h): binding score in [0, 100]. Weighted sum of 5 sub-scores per methodology §1-3:
  • lead_time_growth
  • capacity_tightness
  • geo_concentration
  • regulatory_friction
  • demand_signal

≥ 70  binding bottleneck (PEAKING / PEAKED / RESOLVING)
≥ 50  basket-eligible (screener filter)
< 50  watchlist only

B' (momentum): 6mo backward delta in B.`;

// Hardcoded slug → human-readable title. Mirrors the
// backend `app/segments_meta.py` dict. Kept in sync by hand
// (the canonical source is the `# Title` line in
// research/01_segments/<slug>.md). Used as a fallback when
// the API response doesn't carry a `name` field — e.g.
// the ticker detail page that calls /tickers/X (no `name`).
const _SLUG_TO_NAME: Record<string, string> = {
  advanced_node_fabs: "Advanced-Node Fabs",
  advanced_packaging: "Advanced Packaging (CoWoS / 2.5D / 3D)",
  cooling_water: "Cooling & Water",
  data_center_shell: "Data Center Shell (Colo + Hyperscaler Self-Build)",
  gpu_asic_silicon: "GPU / ASIC Silicon",
  hbm_memory: "HBM Memory",
  networking_interconnect: "Networking & Interconnect",
  power_generation_oem: "Power Generation OEM",
  systems_rack_scale: "Systems OEM/ODM",
  transformers_tnd: "Transformers & Switchgear (T&D)",
};

export function displayName(slug: string | null | undefined): string {
  if (!slug) return "";
  return _SLUG_TO_NAME[slug] ?? slug;
}
