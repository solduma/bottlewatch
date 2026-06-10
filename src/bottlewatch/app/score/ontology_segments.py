"""Segment-to-ontology-role-class bridge.

Maps each scoring segment slug (the keys in `scoring_seed.json`)
to the corresponding TBox role class in `research/05_ontology/bottlewatch.owl`.
Used by `extractors.geo_concentration` to build a SPARQL query
per segment, and by the recompute job to pre-compute one HHI per
segment in a single pass.

The mapping mirrors the segment→role entries in
`jobs/build_ontology.py::_DEFAULT_SEGMENT_TO_ROLE` for the
research-agent taxonomy (the v1 segments). Keeping this as a
separate module means the ontology-derived extractors don't have
to import the build script (which has a hard dependency on the
research CSVs).
"""

from __future__ import annotations

SEGMENT_TO_ROLE_CLASS: dict[str, str] = {
    "advanced_node_fabs": "Foundry",
    "advanced_packaging": "OSAT",
    "cooling_water": "ElectricalEquipmentMaker",
    "data_center_shell": "IDCOperator",
    "gpu_asic_silicon": "GPUDesigner",
    "hbm_memory": "IDM",
    "networking_interconnect": "NetworkingSiliconDesigner",
    "power_generation_oem": "PowerEquipmentOEM",
    "systems_rack_scale": "RackIntegrator",
    "transformers_tnd": "ElectricalEquipmentMaker",
}
