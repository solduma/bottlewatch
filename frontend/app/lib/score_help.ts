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
  // Existing 10 segments
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

  // Added 5 segments
  raw_inputs: "Raw Materials & Commodities",
  fuel_power_inputs: "Fuel & Power Inputs",
  td_utilities: "Transmission & Distribution Utilities",
  semiconductor_materials: "Semiconductor Materials",
  inference_at_scale: "Inference at Scale",

  // Remaining 49 non-scoring nodes
  cool_chillers: "Cooling Chillers",
  cool_pumps: "Cooling Pumps",
  cool_water_treatment: "Cooling Water Treatment",
  fab_process_chemicals: "Fab Process Chemicals",
  fab_utilities: "Fab Utilities",
  fee_optical_components: "Front-End Optical Components",
  fee_vacuum_pumps: "Front-End Vacuum Pumps",
  fee_vacuum_robotics: "Front-End Vacuum Robotics",
  front_end_equipment: "Front-End Equipment",
  fuel_mining: "Fuel Mining",
  fuel_oil_gas: "Fuel Oil & Gas",
  fuel_renewables: "Fuel Renewables",
  fuel_uranium: "Fuel Uranium",
  gen_gas_turbines: "Gas Turbines",
  gen_rare_earths: "Rare Earth Minerals",
  gen_smr: "Small Modular Reactors (SMR)",
  gen_solar: "Solar Power",
  gen_wind: "Wind Power",
  hbm_dram_platform: "HBM DRAM Platform",
  hbm_tsv_equipment: "HBM TSV Equipment",
  inf_enterprise_saas: "Enterprise SaaS",
  inf_neocloud: "Neocloud",
  mat_cmp_slurries: "CMP Slurries",
  mat_photoresist: "Photoresist",
  mat_process_gases: "Process Gases",
  mat_silicon_wafers: "Silicon Wafers",
  net_high_speed_pcb: "High-Speed PCB",
  net_optical_transceivers: "Optical Transceivers",
  net_switch_asics: "Switch ASICs",
  pkg_substrates: "Packaging Substrates",
  pkg_ubm: "Under Bump Metallization (UBM)",
  rack_busbars: "Rack Busbars",
  rack_cdu: "Rack CDU",
  raw_mining: "Raw Mining",
  raw_nuclear_fuel: "Raw Nuclear Fuel",
  raw_oil_gas: "Raw Oil & Gas",
  raw_water_utilities: "Raw Water Utilities",
  shell_colo_reits: "Colocation REITs",
  shell_dark_fiber: "Dark Fiber",
  shell_land_reits: "Land REITs",
  sil_ip_eda: "IP & EDA",
  sil_power_delivery: "Power Delivery",
  sys_chassis: "Chassis",
  sys_psu: "Power Supply Units (PSU)",
  systems_oem_odm: "Systems OEM/ODM",
  tnd_copper: "Copper",
  tnd_electrical_steel: "Electrical Steel",
  tnd_insulation: "Insulation",
  util_regulators: "Regulators",
};

export function displayName(slug: string | null | undefined): string {
  if (!slug) return "";
  return _SLUG_TO_NAME[slug] ?? slug;
}
