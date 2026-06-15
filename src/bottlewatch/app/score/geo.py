"""Universe-based geographic concentration (HHI) for scoring.

Replaces the ontology role-count HHI with an exposure × market-cap
weighted HHI computed directly from `research/02_universe.csv`, plus
curated `operatesIn` overrides for cases where exchange geography is
wrong or a company has multiple listings.

Public entry point:
    geo_concentration(segment, universe_path, overrides_path) -> float | None
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Shared exchange -> default home region map. This is the source of
# truth used both here and by the ontology builder (jobs/build_ontology.py
# imports it).
_EXCHANGE_TO_REGION: dict[str, str] = {
    "NYSE": "NorthAmerica",
    "NASDAQ": "NorthAmerica",
    "NYSEMKT": "NorthAmerica",
    "AMEX": "NorthAmerica",
    "OTCQX": "NorthAmerica",
    "TSE": "Japan",
    "TYO": "Japan",
    "KRX": "Korea",
    "KOSPI": "Korea",
    "TWSE": "Taiwan",
    "FRA": "Europe",
    "XETRA": "Europe",
    "ETR": "Europe",
    "EPA": "Europe",
    "BME": "Europe",
    "OSLO": "Europe",
    "LSE": "Europe",
    "SIX": "Europe",
    "SSE": "GreaterChina",
    "SZSE": "GreaterChina",
    "HKEX": "GreaterChina",
    "BSE": "GreaterChina",
    "NSE": "GreaterChina",
    "ASX": "SoutheastAsia",
    "SGX": "SoutheastAsia",
    "TADAWUL": "MiddleEast",
    "OTHER": "NorthAmerica",
}

# Methodology §2.3 floor: regions with <5% share are treated as
# effectively zero.
_HHI_FLOOR_SHARE = 0.05

# Project root: src/bottlewatch/app/score/geo.py -> ../../../..
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_UNIVERSE_PATH = _PROJECT_ROOT / "research" / "02_universe.csv"
_DEFAULT_OVERRIDES_PATH = _PROJECT_ROOT / "research" / "07_geo_overrides.json"


def _load_geo_overrides(path: Path | None) -> dict[str, Any]:
    """Load curated region overrides indexed by ticker or name."""
    path = path or _DEFAULT_OVERRIDES_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _LOGGER.warning("could not parse geo overrides at %s: %s", path, e)
        return {}
    return data.get("overrides", {})


def _load_universe(path: Path | None) -> list[dict[str, Any]]:
    """Read the universe CSV and return typed rows."""
    path = path or _DEFAULT_UNIVERSE_PATH
    if not path.exists():
        _LOGGER.warning("universe CSV missing at %s; cannot compute HHI", path)
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _region_for_row(
    row: dict[str, Any],
    overrides: dict[str, Any],
) -> str | None:
    """Return the region for a universe row, applying overrides first."""
    ticker = (row.get("ticker") or "").strip()
    name = (row.get("name") or "").strip()
    override = overrides.get(ticker) or overrides.get(name)
    if override:
        return override.get("region")
    exchange = (row.get("exchange") or "").strip()
    return _EXCHANGE_TO_REGION.get(exchange)


def _company_key(
    row: dict[str, Any],
    overrides: dict[str, Any],
) -> str:
    """Return a canonical grouping key for deduplicating listings.

    The default key is the ticker. If the override file declares a
    `parent` for this ticker or name, rows with the same parent are
    merged (weights summed) and assigned the override region.
    """
    ticker = (row.get("ticker") or "").strip()
    name = (row.get("name") or "").strip()
    override = overrides.get(ticker) or overrides.get(name)
    if override:
        parent = override.get("parent")
        if parent:
            return str(parent)
    return ticker if ticker else name


def _hhi_from_weights(weights: dict[str, float]) -> float | None:
    """HHI from per-region weights.

    Applies the 5% share floor, renormalizes the remainder, and returns
    the sum of squared shares. Returns None if no region survives the
    floor.
    """
    if not weights:
        return None
    total = sum(weights.values())
    if total <= 0:
        return None
    qualifying = {region: w for region, w in weights.items() if w / total >= _HHI_FLOOR_SHARE}
    if not qualifying:
        return None
    q_total = sum(qualifying.values())
    if q_total <= 0:
        return None
    return sum((w / q_total) ** 2 for w in qualifying.values())


def geo_concentration(
    segment: str,
    universe_path: Path | None = None,
    overrides_path: Path | None = None,
) -> float | None:
    """Compute exposure × market-cap weighted HHI for a segment.

    Steps:
      1. Load universe rows for this segment.
      2. Group rows by canonical company key (ticker or override
         parent) and assign a region.
      3. Sum exposure_pct × mcap_usd per region.
      4. Apply 5% floor and compute HHI.

    Returns None when the segment has no universe rows or no region
    assignment.
    """
    rows = _load_universe(universe_path)
    overrides = _load_geo_overrides(overrides_path)

    region_weights: dict[str, float] = {}
    for row in rows:
        if (row.get("segment") or "").strip() != segment:
            continue
        try:
            exposure = float(row.get("exposure_pct") or 0) / 100.0
            mcap = float(row.get("mcap_usd") or 0)
        except (TypeError, ValueError):
            continue
        if exposure <= 0 or mcap <= 0:
            continue
        region = _region_for_row(row, overrides)
        if region is None:
            continue
        key = _company_key(row, overrides)
        # Use the override region for the parent if one exists, else the
        # row's own region. When a parent groups multiple listings, the
        # override file is expected to declare a single region for the
        # parent ticker/name; otherwise we use the largest-mcap row's
        # region (last-write-wins here, the override is authoritative).
        override = overrides.get(key)
        if override and "region" in override:
            region = override["region"]
        weight = exposure * mcap
        region_weights[region] = region_weights.get(region, 0.0) + weight

    return _hhi_from_weights(region_weights)
