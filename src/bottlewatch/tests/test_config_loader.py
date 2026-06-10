"""Tests for the JSON config loader (app/config_loader.py)."""

from __future__ import annotations


from bottlewatch.app.config_loader import (
    load_eta_table,
    load_eia_series_spec,
    load_eia_states,
)


def test_load_eta_table_has_all_ten_segments() -> None:
    """All 10 scoring segments must be in the ETA JSON; the API
    falls back to None (no band) for segments not in the table.
    """
    expected = {
        "advanced_node_fabs",
        "advanced_packaging",
        "cooling_water",
        "data_center_shell",
        "gpu_asic_silicon",
        "hbm_memory",
        "networking_interconnect",
        "power_generation_oem",
        "systems_rack_scale",
        "transformers_tnd",
    }
    table = load_eta_table()
    assert set(table.keys()) == expected


def test_load_eta_table_band_is_valid() -> None:
    for seg, info in load_eta_table().items():
        assert info["eta"] in {"<12mo", "12-24mo", ">24mo"}, seg
        assert info["confidence"] in {"low", "medium", "high"}, seg


def test_load_eia_series_spec_returns_m2_baseline() -> None:
    spec = load_eia_series_spec()
    assert isinstance(spec, list)
    assert len(spec) >= 1
    series_ids = {s["series_id"] for s in spec}
    # The M2 spec covers net generation and TX retail sales.
    assert "ELEC.GEN.ALL-US-99.A" in series_ids
    assert "ELEC.SALES.TX-RES.M" in series_ids
    for entry in spec:
        assert "segment" in entry
        assert "signal_name" in entry
        assert "unit" in entry
        assert "value_column" in entry


def test_load_eia_states_is_50_plus_dc() -> None:
    states = load_eia_states()
    assert isinstance(states, tuple)
    assert len(states) == 51
    assert "DC" in states
    # Spot-check a few well-known state codes.
    for s in ("CA", "TX", "NY", "FL", "AK", "HI"):
        assert s in states, s
