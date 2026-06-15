"""Human-readable display names for segment slugs.

The canonical source for these names is the `# Title` line at
the top of each `research/01_segments/<slug>.md` file. This
module is a one-time copy that the operator maintains alongside
the research artifacts — same pattern as
`app/score/ontology_segments.py:SEGMENT_TO_ROLE_CLASS`.

Slugs not in the dict fall back to the slug itself, so
adding a new segment to `scoring_seed.json` without
updating this dict degrades to the variable name
(visible, but ugly) rather than throwing.
"""

from __future__ import annotations
import json
from pathlib import Path

# Project root: src/bottlewatch/app/segments_meta.py -> ../../../..
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_VALUE_CHAIN_JSON = _PROJECT_ROOT / "research" / "00_value_chain.json"

# Slug → human-readable title. Values mirror the `# Title`
# line in research/01_segments/<slug>.md.
_SEGMENT_NAMES: dict[str, str] = {
    # Original 10 segments
    "advanced_node_fabs": "Advanced-Node Fabs",
    "advanced_packaging": "Advanced Packaging (CoWoS / 2.5D / 3D)",
    "cooling_water": "Cooling & Water",
    "data_center_shell": "Data Center Shell (Colo + Hyperscaler Self-Build)",
    "gpu_asic_silicon": "GPU / ASIC Silicon",
    "hbm_memory": "HBM Memory",
    "networking_interconnect": "Networking & Interconnect",
    "power_generation_oem": "Power Generation OEM",
    "systems_rack_scale": "Systems OEM/ODM",
    "transformers_tnd": "Transformers & Switchgear (T&D)",
    # Added 5 segments
    "raw_inputs": "Raw Materials & Commodities",
    "fuel_power_inputs": "Fuel & Power Inputs",
    "td_utilities": "Transmission & Distribution Utilities",
    "semiconductor_materials": "Semiconductor Materials",
    "inference_at_scale": "Inference at Scale",
    # Remaining 49 non-scoring nodes turned scoring segments
    "cool_chillers": "Cooling Chillers",
    "cool_pumps": "Cooling Pumps",
    "cool_water_treatment": "Cooling Water Treatment",
    "fab_process_chemicals": "Fab Process Chemicals",
    "fab_utilities": "Fab Utilities",
    "fee_optical_components": "Front-End Optical Components",
    "fee_vacuum_pumps": "Front-End Vacuum Pumps",
    "fee_vacuum_robotics": "Front-End Vacuum Robotics",
    "front_end_equipment": "Front-End Equipment",
    "fuel_mining": "Fuel Mining",
    "fuel_oil_gas": "Fuel Oil & Gas",
    "fuel_renewables": "Fuel Renewables",
    "fuel_uranium": "Fuel Uranium",
    "gen_gas_turbines": "Gas Turbines",
    "gen_rare_earths": "Rare Earth Minerals",
    "gen_smr": "Small Modular Reactors (SMR)",
    "gen_solar": "Solar Power",
    "gen_wind": "Wind Power",
    "hbm_dram_platform": "HBM DRAM Platform",
    "hbm_tsv_equipment": "HBM TSV Equipment",
    "inf_enterprise_saas": "Enterprise SaaS",
    "inf_neocloud": "Neocloud",
    "mat_cmp_slurries": "CMP Slurries",
    "mat_photoresist": "Photoresist",
    "mat_process_gases": "Process Gases",
    "mat_silicon_wafers": "Silicon Wafers",
    "net_high_speed_pcb": "High-Speed PCB",
    "net_optical_transceivers": "Optical Transceivers",
    "net_switch_asics": "Switch ASICs",
    "pkg_substrates": "Packaging Substrates",
    "pkg_ubm": "Under Bump Metallization (UBM)",
    "rack_busbars": "Rack Busbars",
    "rack_cdu": "Rack CDU",
    "raw_mining": "Raw Mining",
    "raw_nuclear_fuel": "Raw Nuclear Fuel",
    "raw_oil_gas": "Raw Oil & Gas",
    "raw_water_utilities": "Raw Water Utilities",
    "shell_colo_reits": "Colocation REITs",
    "shell_dark_fiber": "Dark Fiber",
    "shell_land_reits": "Land REITs",
    "sil_ip_eda": "IP & EDA",
    "sil_power_delivery": "Power Delivery",
    "sys_chassis": "Chassis",
    "sys_psu": "Power Supply Units (PSU)",
    "systems_oem_odm": "Systems OEM/ODM",
    "tnd_copper": "Copper",
    "tnd_electrical_steel": "Electrical Steel",
    "tnd_insulation": "Insulation",
    "util_regulators": "Regulators",
}

# Segment slug → sector. Loaded from research/00_value_chain.json
# which is the source of truth for the value chain's sector structure.
_SEGMENT_TO_SECTOR: dict[str, str] = {}


def load_value_chain_sectors() -> dict[str, str]:
    """Load segment → sector mapping from value chain JSON."""
    global _SEGMENT_TO_SECTOR
    if _SEGMENT_TO_SECTOR:
        return _SEGMENT_TO_SECTOR

    try:
        with open(_VALUE_CHAIN_JSON, encoding="utf-8") as f:
            chain = json.load(f)

        for node in chain["nodes"]:
            _SEGMENT_TO_SECTOR[node["id"]] = node["sector"]

        return _SEGMENT_TO_SECTOR
    except Exception as e:
        from logging import warning

        warning(f"Failed to load value chain sectors: {e}")
        return {}


def sector_for_segment(slug: str) -> str:
    """Return the sector for a segment slug, or fallback to 'Unknown'."""
    sectors = load_value_chain_sectors()
    return sectors.get(slug, "Unknown")


def display_name(slug: str) -> str:
    """Return the human-readable name for a segment slug.

    Falls back to the slug itself when no mapping exists, so
    a newly-added segment stays visible (if unstyled) rather
    than throwing.
    """
    return _SEGMENT_NAMES.get(slug, slug)
