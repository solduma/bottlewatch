"""Tests for the Mermaid value-chain generator."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


from bottlewatch.jobs.map_mermaid import (
    ValueChain,
    _escape_label,
    _node_class,
    _regimes_from_json,
    _shorten_label,
    build_mermaid,
    load_chain,
    write_report_meta,
)

# Project root: src/bottlewatch/tests/test_map_mermaid.py -> ../../..
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_CHAIN_PATH = _PROJECT_ROOT / "research" / "00_value_chain.json"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_escape_label_drops_backticks_and_hashes() -> None:
    assert _escape_label("foo `bar` #1") == "foo 'bar' no.1"
    assert _escape_label("multi   spaces   here") == "multi spaces here"
    assert _escape_label("plain label") == "plain label"


def test_shorten_label_truncates_with_ellipsis() -> None:
    assert _shorten_label("short", 30) == "short"
    long = "a" * 50
    out = _shorten_label(long, 30)
    assert len(out) == 30
    assert out.endswith("…")


def test_node_class_prefers_regime_over_sector() -> None:
    # When regime is set, the regime class wins.
    assert _node_class("data_center_shell", "InfrastructureSector", "PEAKED") == "regime_peaked"
    # When regime is None, fall back to the sector.
    assert _node_class("data_center_shell", "InfrastructureSector", None) == "sector_infrastructure"
    # Unknown regime → sector fallback.
    assert _node_class("data_center_shell", "InfrastructureSector", "BOGUS") == "sector_infrastructure"


def test_regimes_from_json_loads_mapping() -> None:
    p = Path("/tmp/regimes_test.json")
    p.write_text(json.dumps({"data_center_shell": "PEAKED", "hbm_memory": "PEAKING"}))
    try:
        out = _regimes_from_json(p)
        assert out == {"data_center_shell": "PEAKED", "hbm_memory": "PEAKING"}
    finally:
        p.unlink()


def test_regimes_from_json_missing_returns_empty(tmp_path: Path) -> None:
    assert _regimes_from_json(tmp_path / "missing.json") == {}


# ---------------------------------------------------------------------------
# load_chain
# ---------------------------------------------------------------------------


def test_load_chain_real_file() -> None:
    chain = load_chain(_CHAIN_PATH)
    assert isinstance(chain, ValueChain)
    # The value chain has been growing with each iteration; the test
    # only pins the shape (non-empty, sane edge count) rather than the
    # exact totals so it doesn't break every time someone adds a
    # supplier leaf.
    assert len(chain.nodes) >= 16
    assert len(chain.edges) >= 16
    assert "HardwareSector" in chain.sectors


def test_load_chain_missing_returns_empty(tmp_path: Path) -> None:
    chain = load_chain(tmp_path / "missing.json")
    assert chain.nodes == []
    assert chain.edges == []
    assert chain.sectors == {}


# ---------------------------------------------------------------------------
# build_mermaid
# ---------------------------------------------------------------------------


def _ids_in_source(source: str) -> set[str]:
    """Return the set of Mermaid node ids (the bare identifier at the start of a line)."""
    return set(re.findall(r"^\s{2,4}([a-z][a-z0-9_]*)\s*[\[\(]", source, re.MULTILINE))


def test_build_mermaid_contains_all_node_ids() -> None:
    chain = load_chain(_CHAIN_PATH)
    src = build_mermaid(chain)
    declared = _ids_in_source(src)
    expected = {n["id"] for n in chain.nodes}
    missing = expected - declared
    assert not missing, f"node ids not declared: {sorted(missing)[:5]}..."


def test_build_mermaid_emits_all_edges() -> None:
    chain = load_chain(_CHAIN_PATH)
    src = build_mermaid(chain)
    # Count role-kind-agnostic edges by parsing the A --> B form.
    role_edges = [e for e in chain.edges if not e.get("commodity")]
    role_edge_count = len({(e["from"], e["to"]) for e in role_edges})
    # The role edges (no commodity) form a stable count.
    role_arrow_count = len(re.findall(r"^\s+[a-z][a-z0-9_]*\s+-->\s+[a-z][a-z0-9_]*$", src, re.MULTILINE))
    assert role_arrow_count == role_edge_count


def test_build_mermaid_uses_commodity_label_form() -> None:
    chain = load_chain(_CHAIN_PATH)
    src = build_mermaid(chain)
    # At least one commodity edge has a label.
    assert "-->|" in src
    # The label for `mat_process_gases` -> `semiconductor_materials` is `neon_helium_UF6`.
    assert "neon_helium_UF6" in src or "neon helium UF6" in src


def test_build_mermaid_has_one_subgraph_per_sector() -> None:
    chain = load_chain(_CHAIN_PATH)
    src = build_mermaid(chain)
    subgraphs = re.findall(r"^  subgraph (\w+)\[", src, re.MULTILINE)
    # 4 sectors + no `default` bucket because all 57 nodes have a sector.
    assert set(subgraphs) == {"MaterialsSector", "HardwareSector", "InfrastructureSector", "DownstreamSector"}


def test_build_mermaid_escapes_special_chars_in_labels() -> None:
    """Labels with parens, slashes, hashes, backticks should be safe in Mermaid syntax."""
    fake_chain = ValueChain(
        nodes=[
            {"id": "weird", "label": "advanced/node #1 (alpha)", "sector": "HardwareSector", "companies": []},
        ],
        edges=[],
        sectors={"HardwareSector": "hw"},
    )
    src = build_mermaid(fake_chain)
    # The line for `weird` should be safe: identifier, then quoted label.
    m = re.search(r'weird\["([^"]+)"\]', src)
    assert m is not None
    label = m.group(1)
    assert "#" not in label  # we drop `#` in _escape_label
    assert "`" not in label
    # Parens are allowed inside quoted strings; verify they're still there.
    assert "(" in label
    # No raw unescaped `#` in any node-declaration line (classDef
    # lines legitimately use `#` for hex colors — those are fine).
    for line in src.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("classDef", "%%{", "%%")):
            continue
        if "#" in line:
            # `#` must be inside a quoted string (Mermaid's classDef
            # syntax uses `#rrggbb` for fills, but only in classDef
            # lines, which we already skipped).
            assert re.search(r'"[^"]*#[^"]*"', line), f"unescaped `#` in line: {line!r}"


def test_build_mermaid_applies_regime_styling_when_provided() -> None:
    chain = load_chain(_CHAIN_PATH)
    src = build_mermaid(chain, regimes={"data_center_shell": "PEAKED", "hbm_memory": "PEAKING"})
    # The data_center_shell node should be tagged with the regime class.
    assert 'data_center_shell["data center shell"]:::regime_peaked' in src
    assert 'hbm_memory["HBM memory"]:::regime_peaking' in src
    # The classDef for those regimes is emitted.
    assert "classDef regime_peaked" in src
    assert "classDef regime_peaking" in src


def test_build_mermaid_falls_back_to_sector_when_no_regime() -> None:
    chain = load_chain(_CHAIN_PATH)
    src = build_mermaid(chain, regimes={})
    # Without regimes, the data_center_shell node should use the sector class.
    assert 'data_center_shell["data center shell"]:::sector_infrastructure' in src
    # And the classDef block is still emitted.
    assert "classDef sector_infrastructure" in src


def test_build_mermaid_is_deterministic() -> None:
    """Two runs against the same input produce identical output."""
    chain = load_chain(_CHAIN_PATH)
    a = build_mermaid(chain)
    b = build_mermaid(chain)
    assert a == b


# ---------------------------------------------------------------------------
# write_report_meta
# ---------------------------------------------------------------------------


def test_write_report_meta_records_paths_and_sizes(tmp_path: Path) -> None:
    mmd = tmp_path / "x.mmd"
    svg = tmp_path / "x.svg"
    mmd.write_text("flowchart LR\n  A --> B\n")
    svg.write_text("<svg/>")
    write_report_meta(svg, mmd)
    meta = json.loads(mmd.with_suffix(".meta.json").read_text())
    assert meta["mmd_bytes"] == len("flowchart LR\n  A --> B\n")
    assert meta["svg_bytes"] == len("<svg/>")
    # Paths are recorded as strings (absolute when outside the
    # project root, relative when inside).
    assert isinstance(meta["mmd_path"], str)
    assert isinstance(meta["svg_path"], str)
    assert "ts" in meta
    assert isinstance(meta["mmdc_available"], bool)


def test_write_report_meta_handles_missing_svg(tmp_path: Path) -> None:
    mmd = tmp_path / "x.mmd"
    mmd.write_text("flowchart LR\n")
    write_report_meta(None, mmd)
    meta = json.loads(mmd.with_suffix(".meta.json").read_text())
    assert meta["svg_path"] is None
    assert meta["svg_bytes"] is None
    assert meta["mmd_bytes"] is not None


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


def test_cli_writes_mmd_and_exits_zero(tmp_path: Path) -> None:
    """The CLI runs end-to-end on the real value chain and writes a .mmd."""
    output = tmp_path / "value-chain.mmd"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bottlewatch.jobs.map_mermaid",
            "--no-render",
            "--mmd",
            str(output),
        ],
        capture_output=True,
        text=True,
        cwd=str(_PROJECT_ROOT),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert output.exists()
    content = output.read_text()
    # Sanity: contains the expected header and at least one node + edge.
    assert content.startswith("%%{init:")
    assert "flowchart LR" in content
    assert "advanced_node_fabs" in content
    assert "-->" in content
