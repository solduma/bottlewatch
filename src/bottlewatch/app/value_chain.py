"""Shared value-chain accessors (M2 stopgap).

The research artifact `research/00_value_chain.json` is the
machine-readable source of truth for the value chain. Three
runtime modules read it:

- `bottlewatch.jobs.map_mermaid` — emits Mermaid + SVG.
- `bottlewatch.app.api.map` — serves it to the React `/map` page.
- `bottlewatch.app.api.tickers` — looks up the value-chain
  `companies` list for the ticker's segment.

A subtle drift caught us in M2: the value-chain JSON uses node
ids like `transformers_switchgear` and `rack_scale_integration`,
but the scoring layer (the `Score` table) uses slugs
`transformers_tnd` and `systems_rack_scale`. The translation
between the two lives in `NODE_ID_TO_SEGMENT` /
`SEGMENT_TO_NODE_ID` below, defined in one place and imported
by every consumer. Adding a new segment is a one-line change
here.

The two constants are the inverse of each other; the helper
`load_value_chain_json()` is the single read path so a future
move to a real DB table can be a one-function swap.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

# Project root: src/bottlewatch/app/value_chain.py -> ../../../..
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CHAIN = _PROJECT_ROOT / "research" / "00_value_chain.json"

# Value-chain node id -> scoring segment slug.
# `NodeId` is the JSON key; `segment` matches `Score.segment` and
# `TickerRow.segment` in the API. The reverse map is built from
# this one at import time so the two cannot drift.
NODE_ID_TO_SEGMENT: dict[str, str] = {
    "advanced_node_fabs": "advanced_node_fabs",
    "advanced_packaging": "advanced_packaging",
    "hbm_memory": "hbm_memory",
    "networking_interconnect": "networking_interconnect",
    "gpu_asic_silicon": "gpu_asic_silicon",
    "data_center_shell": "data_center_shell",
    "transformers_switchgear": "transformers_tnd",
    "power_generation_oem": "power_generation_oem",
    "cooling_water": "cooling_water",
    "rack_scale_integration": "systems_rack_scale",
}

# Reverse map: scoring segment slug -> value-chain node id. Built
# at import time so adding a forward entry is the only edit needed.
SEGMENT_TO_NODE_ID: dict[str, str] = {v: k for k, v in NODE_ID_TO_SEGMENT.items()}


def load_value_chain_json(path: Path | None = None) -> dict:
    """Read the value chain JSON, returning an empty dict on missing file.

    The endpoint layer treats an empty dict as "no data"; we don't
    raise because a missing file should be a warning, not a 500.
    """
    chain_path = path or _DEFAULT_CHAIN
    if not chain_path.exists():
        _LOGGER.warning("value chain JSON missing at %s", chain_path)
        return {}
    try:
        return json.loads(chain_path.read_text())
    except json.JSONDecodeError as e:
        _LOGGER.warning("value chain JSON is malformed at %s: %s", chain_path, e)
        return {}
