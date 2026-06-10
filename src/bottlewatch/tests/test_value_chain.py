"""Tests for the shared value-chain accessor (app/value_chain.py)."""

from __future__ import annotations

import json
from pathlib import Path


from bottlewatch.app.value_chain import (
    NODE_ID_TO_SEGMENT,
    SEGMENT_TO_NODE_ID,
    load_value_chain_json,
)


def test_node_id_to_segment_is_inverse_of_segment_to_node_id() -> None:
    """The two maps must be exact inverses; if you add one entry to
    either side without the other, this fails."""
    assert set(NODE_ID_TO_SEGMENT.values()) == set(SEGMENT_TO_NODE_ID.keys())
    for node_id, segment in NODE_ID_TO_SEGMENT.items():
        assert SEGMENT_TO_NODE_ID[segment] == node_id


def test_known_mismatches_are_translated() -> None:
    """Specific assertions for the M2 slug mismatches that
    previously caused silent empty `companies` lists."""
    assert SEGMENT_TO_NODE_ID["transformers_tnd"] == "transformers_switchgear"
    assert SEGMENT_TO_NODE_ID["systems_rack_scale"] == "rack_scale_integration"
    assert NODE_ID_TO_SEGMENT["transformers_switchgear"] == "transformers_tnd"
    assert NODE_ID_TO_SEGMENT["rack_scale_integration"] == "systems_rack_scale"


def test_load_value_chain_json_returns_dict(tmp_path: Path) -> None:
    p = tmp_path / "chain.json"
    p.write_text(json.dumps({"nodes": [{"id": "x", "label": "X"}]}))
    out = load_value_chain_json(p)
    assert out == {"nodes": [{"id": "x", "label": "X"}]}


def test_load_value_chain_json_missing_file_warns_and_returns_empty(tmp_path: Path, caplog) -> None:
    p = tmp_path / "does-not-exist.json"
    with caplog.at_level("WARNING"):
        out = load_value_chain_json(p)
    assert out == {}
    assert "value chain JSON missing" in caplog.text


def test_load_value_chain_json_malformed_warns_and_returns_empty(tmp_path: Path, caplog) -> None:
    p = tmp_path / "broken.json"
    p.write_text("{not valid json")
    with caplog.at_level("WARNING"):
        out = load_value_chain_json(p)
    assert out == {}
    assert "malformed" in caplog.text
