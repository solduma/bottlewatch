"""Shared JSON config loader (research/config/*.json).

The research artifact directory `research/config/` holds small
JSON files for tables that are too unwieldy to inline in Python
modules but not large enough to live in the database:

- `eta.json` — resolution ETA bands per segment
- `eia_series_spec.json` — EIA v2 series → segment mapping
- `eia_states.json` — 50-state list for EIA capacity aggregation

The loader fails fast on missing or malformed files; calibration
typos should crash the process at import time, not at run time.

The load functions are intentionally narrow: each file has a
specific shape and we read it as `Any` then let the consumer
type-check. We don't use pydantic for these (small, well-known
shapes) — pydantic's overhead isn't worth the precision.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Project root: src/bottlewatch/app/config_loader.py -> ../../../..  (4 levels)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_DIR = _PROJECT_ROOT / "research" / "config"


def _load_json(name: str) -> Any:
    """Read a JSON config file by basename. Raises on missing/malformed.

    Top-level keys starting with `_` are treated as human-readable
    annotations and stripped before returning. This is the
    convention used by all `research/config/*.json` files for the
    `_comment` field; the loader keeps the consumer side clean
    (a comprehension over `load_eta_table().items()` only sees
    real segment keys, not the comment).
    """
    path = _CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"config file not found at {path}; expected research/config/{name}")
    raw = json.loads(path.read_text())
    if isinstance(raw, dict):
        return {k: v for k, v in raw.items() if not k.startswith("_")}
    return raw


def load_eta_table() -> dict[str, dict[str, str]]:
    """Return {segment: {"eta": band, "confidence": level}}."""
    return _load_json("eta.json")


def load_score_bands() -> dict[str, dict[str, Any]]:
    """Return {sub_score: {source_key: band_spec}} from research/config/score_bands.json.

    Band specs are used by extractors and the normalizer to map raw
    signals to [0, 1]. The loader strips top-level `_` annotations.
    """
    return _load_json("score_bands.json")


def load_eia_series_spec() -> list[dict[str, Any]]:
    """Return the EIA v2 series spec list (one dict per series)."""
    return _load_json("eia_series_spec.json")


def load_eia_states() -> tuple[str, ...]:
    """Return the 50-state + DC list as a tuple (preserves iteration order)."""
    return tuple(_load_json("eia_states.json"))
