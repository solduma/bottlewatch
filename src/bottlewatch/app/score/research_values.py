"""Loader for research/scoring_seed.json.

The seed file is a hand-written map from segment slug to the 4
sub-scores that are NOT computed from the `signals` table in M2.
The 5th sub-score (`capacity_tightness`) lives in `extractors.py`.

`load_seed()` reads the JSON file once per call. The recompute job
calls it 33 times (10 segments × 3 horizons + a few safety checks);
we cache the parsed dict at module level to keep that cheap.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

_PROJECT_ROOT = Path(__file__).resolve().parents[4]  # src/bottlewatch/app/score/...
_DEFAULT_SEED_PATH = _PROJECT_ROOT / "research" / "scoring_seed.json"


class SeedEntry(TypedDict):
    lead_time_growth: float
    geo_concentration: float
    regulatory_friction: float
    demand_signal: float


Seed = dict[str, SeedEntry]


@lru_cache(maxsize=1)
def _load_seed_from(path: str) -> Seed:
    with Path(path).open() as f:
        return json.load(f)


def load_seed(path: Path | None = None) -> Seed:
    """Return the parsed seed JSON. Module-level cache keeps
    repeated calls cheap.
    """
    return _load_seed_from(str(path or _DEFAULT_SEED_PATH))


def for_segment(segment: str, seed: Seed | None = None) -> SeedEntry:
    """Return the 4 research sub-scores for one segment.

    Raises KeyError if the segment slug is missing from the seed
    file. The recompute job treats this as a hard error (a segment
    without research values is a config bug, not a runtime issue).
    """
    s = seed if seed is not None else load_seed()
    return s[segment]


def known_segments(seed: Seed | None = None) -> list[str]:
    """Return the list of segment slugs in the seed file. The
    recompute job iterates this to build the 30-row scores table.
    """
    s = seed if seed is not None else load_seed()
    return [k for k in s if not k.startswith("_")]
