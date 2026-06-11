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

# Slug → human-readable title. Values mirror the `# Title`
# line in research/01_segments/<slug>.md.
_SEGMENT_NAMES: dict[str, str] = {
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
}


def display_name(slug: str) -> str:
    """Return the human-readable name for a segment slug.

    Falls back to the slug itself when no mapping exists, so
    a newly-added segment stays visible (if unstyled) rather
    than throwing.
    """
    return _SEGMENT_NAMES.get(slug, slug)
