"""Tests for app/score/geo.py — universe-weighted HHI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bottlewatch.app.score import geo as geo_module


def _make_universe_csv(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    path = tmp_path / "universe.csv"
    header = [
        "ticker",
        "exchange",
        "name",
        "segment",
        "subsegment",
        "exposure_pct",
        "market_cap_bucket",
        "mcap_usd",
        "currency_hedge",
        "notes",
    ]
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join([str(row.get(c, "")) for c in header]))
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _make_overrides_json(tmp_path: Path, overrides: dict[str, Any]) -> Path:
    path = tmp_path / "overrides.json"
    import json

    path.write_text(json.dumps({"overrides": overrides}), encoding="utf-8")
    return path


def test_single_region_is_fully_concentrated(tmp_path: Path) -> None:
    csv = _make_universe_csv(
        tmp_path,
        [
            {
                "ticker": "A",
                "exchange": "NYSE",
                "name": "A",
                "segment": "advanced_node_fabs",
                "exposure_pct": 100,
                "mcap_usd": 100,
            },
            {
                "ticker": "B",
                "exchange": "NYSE",
                "name": "B",
                "segment": "advanced_node_fabs",
                "exposure_pct": 100,
                "mcap_usd": 100,
            },
        ],
    )
    hhi = geo_module.geo_concentration("advanced_node_fabs", universe_path=csv)
    assert hhi == pytest.approx(1.0)


def test_two_equal_regions(tmp_path: Path) -> None:
    csv = _make_universe_csv(
        tmp_path,
        [
            {
                "ticker": "A",
                "exchange": "NYSE",
                "name": "A",
                "segment": "advanced_node_fabs",
                "exposure_pct": 100,
                "mcap_usd": 100,
            },
            {
                "ticker": "B",
                "exchange": "TWSE",
                "name": "B",
                "segment": "advanced_node_fabs",
                "exposure_pct": 100,
                "mcap_usd": 100,
            },
        ],
    )
    hhi = geo_module.geo_concentration("advanced_node_fabs", universe_path=csv)
    assert hhi == pytest.approx(0.5)


def test_exposure_times_mcap_weighted(tmp_path: Path) -> None:
    csv = _make_universe_csv(
        tmp_path,
        [
            # Two US companies: combined weight 100 * 10B = 1T
            {
                "ticker": "A",
                "exchange": "NYSE",
                "name": "A",
                "segment": "advanced_node_fabs",
                "exposure_pct": 100,
                "mcap_usd": 500_000_000_000,
            },
            {
                "ticker": "B",
                "exchange": "NYSE",
                "name": "B",
                "segment": "advanced_node_fabs",
                "exposure_pct": 100,
                "mcap_usd": 500_000_000_000,
            },
            # One TW company: weight 100 * 1B = 100B
            {
                "ticker": "C",
                "exchange": "TWSE",
                "name": "C",
                "segment": "advanced_node_fabs",
                "exposure_pct": 100,
                "mcap_usd": 100_000_000_000,
            },
        ],
    )
    hhi = geo_module.geo_concentration("advanced_node_fabs", universe_path=csv)
    us_share = 1000 / 1100
    tw_share = 100 / 1100
    expected = us_share**2 + tw_share**2
    assert hhi == pytest.approx(expected)


def test_floor_drops_small_regions(tmp_path: Path) -> None:
    csv = _make_universe_csv(
        tmp_path,
        [
            {
                "ticker": "A",
                "exchange": "NYSE",
                "name": "A",
                "segment": "advanced_node_fabs",
                "exposure_pct": 100,
                "mcap_usd": 96,
            },
            {
                "ticker": "B",
                "exchange": "TWSE",
                "name": "B",
                "segment": "advanced_node_fabs",
                "exposure_pct": 100,
                "mcap_usd": 4,
            },
        ],
    )
    hhi = geo_module.geo_concentration("advanced_node_fabs", universe_path=csv)
    assert hhi == pytest.approx(1.0)


def test_override_changes_region(tmp_path: Path) -> None:
    csv = _make_universe_csv(
        tmp_path,
        [
            {
                "ticker": "TSM",
                "exchange": "NYSE",
                "name": "TSM",
                "segment": "advanced_node_fabs",
                "exposure_pct": 100,
                "mcap_usd": 100,
            },
            {
                "ticker": "INTC",
                "exchange": "NASDAQ",
                "name": "INTC",
                "segment": "advanced_node_fabs",
                "exposure_pct": 100,
                "mcap_usd": 100,
            },
        ],
    )
    overrides = _make_overrides_json(
        tmp_path,
        {"TSM": {"region": "Taiwan", "reason": "primary TWSE listing"}},
    )
    hhi = geo_module.geo_concentration("advanced_node_fabs", universe_path=csv, overrides_path=overrides)
    assert hhi == pytest.approx(0.5)


def test_parent_dedup_merges_listings(tmp_path: Path) -> None:
    csv = _make_universe_csv(
        tmp_path,
        [
            {
                "ticker": "TSM",
                "exchange": "NYSE",
                "name": "TSM",
                "segment": "advanced_node_fabs",
                "exposure_pct": 90,
                "mcap_usd": 100,
            },
            {
                "ticker": "2330.TW",
                "exchange": "TWSE",
                "name": "TSMC",
                "segment": "advanced_node_fabs",
                "exposure_pct": 95,
                "mcap_usd": 100,
            },
            {
                "ticker": "INTC",
                "exchange": "NASDAQ",
                "name": "INTC",
                "segment": "advanced_node_fabs",
                "exposure_pct": 100,
                "mcap_usd": 100,
            },
        ],
    )
    overrides = _make_overrides_json(
        tmp_path,
        {
            "TSM": {"region": "Taiwan", "parent": "TSMC_GROUP"},
            "2330.TW": {"region": "Taiwan", "parent": "TSMC_GROUP"},
        },
    )
    hhi = geo_module.geo_concentration("advanced_node_fabs", universe_path=csv, overrides_path=overrides)
    # TSMC group combined weight = 90 + 95 = 185; INTC = 100
    # Total = 285; Taiwan share = 185/285; US share = 100/285
    tw_share = 185 / 285
    us_share = 100 / 285
    expected = tw_share**2 + us_share**2
    assert hhi == pytest.approx(expected)


def test_missing_segment_returns_none(tmp_path: Path) -> None:
    csv = _make_universe_csv(tmp_path, [])
    assert geo_module.geo_concentration("not_a_segment", universe_path=csv) is None


def test_unknown_exchange_drops_row(tmp_path: Path) -> None:
    csv = _make_universe_csv(
        tmp_path,
        [
            {
                "ticker": "A",
                "exchange": "UNKNOWN",
                "name": "A",
                "segment": "advanced_node_fabs",
                "exposure_pct": 100,
                "mcap_usd": 100,
            },
        ],
    )
    assert geo_module.geo_concentration("advanced_node_fabs", universe_path=csv) is None
