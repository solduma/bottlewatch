"""Mermaid SVG fallback for the value chain map.

The interactive React `/map` page is great for navigation but
cannot be shared as a static artifact (no SVG export, no copy-paste
to a thesis doc). This job reads `research/00_value_chain.json`
and emits a Mermaid `flowchart LR` source file plus, when
`mmdc` is on PATH, a rendered SVG.

The .mmd is the canonical, hand-portable artifact. Paste it into
mermaid.live, hackpad, or any Markdown renderer. The .svg is the
shareable static image.

Usage:
    uv run bottlewatch-map-mermaid
    uv run bottlewatch-map-mermaid --no-render   # .mmd only
    uv run bottlewatch-map-mermaid --regimes regimes.json  # color nodes by regime
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bottlewatch.app.value_chain import NODE_ID_TO_SEGMENT

_LOGGER = logging.getLogger(__name__)

# Project root: src/bottlewatch/jobs/map_mermaid.py -> ../../..
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CHAIN = _PROJECT_ROOT / "research" / "00_value_chain.json"
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "data" / "cache"

# Node-id → scoring segment slug map.
#
# The value chain uses snake_case node ids like `advanced_node_fabs`
# for segments that match `Score.segment`. Some nodes (e.g.
# `raw_inputs`, `fuel_power_inputs`) are not scoring segments — they
# get regime = None and fall through to the no-color path.
#
# The full chain has 57 nodes; only the 10 scoring segments + a
# handful of near-synonyms need a mapping. The mapping lives in
# `bottlewatch.app.value_chain.NODE_ID_TO_SEGMENT` and is imported
# above; this alias keeps the existing `_NODE_TO_SEGMENT` call sites
# in this file unchanged.
_NODE_TO_SEGMENT = NODE_ID_TO_SEGMENT

# Mermaid classDef styles per regime. The class names are referenced
# from each node declaration.
_REGIME_CLASSDEF = {
    "PEAKING": "fill:#fee2e2,stroke:#ef4444,color:#7f1d1d",
    "PEAKED": "fill:#ffedd5,stroke:#f97316,color:#7c2d12",
    "RESOLVING": "fill:#d1fae5,stroke:#10b981,color:#064e3b",
    "EMERGING": "fill:#dbeafe,stroke:#3b82f6,color:#1e3a8a",
    "STABLE": "fill:#f3f4f6,stroke:#6b7280,color:#1f2937",
    "RESOLVING_FROM_LOW": "fill:#ccfbf1,stroke:#14b8a6,color:#134e4a",
    "NO_DATA": "fill:#f9fafb,stroke:#d1d5db,color:#6b7280",
}

# Sector subgraph fills. Distinct enough to read at a glance; kept
# muted so node regime colors (when applied) still pop.
_SECTOR_CLASSDEF = {
    "MaterialsSector": "fill:#fef3c7,stroke:#d97706,color:#451a03",
    "HardwareSector": "fill:#e0e7ff,stroke:#4f46e5,color:#1e1b4b",
    "InfrastructureSector": "fill:#dcfce7,stroke:#16a34a,color:#052e16",
    "DownstreamSector": "fill:#fce7f3,stroke:#db2777,color:#500724",
}


@dataclass(frozen=True)
class ValueChain:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    sectors: dict[str, str]


def load_chain(path: Path) -> ValueChain:
    """Read and parse the value chain JSON. Returns empty ValueChain on missing file."""
    if not path.exists():
        _LOGGER.warning("value chain JSON missing at %s", path)
        return ValueChain(nodes=[], edges=[], sectors={})
    with path.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return ValueChain(
        nodes=raw.get("nodes", []),
        edges=raw.get("edges", []),
        sectors=raw.get("sectors", {}),
    )


def _escape_label(s: str) -> str:
    """Escape Mermaid-unsafe characters in node labels.

    Mermaid's quoted-string form (`["..."]`) supports almost any
    character, but `#` and backticks still have meaning. We strip
    them down to a safe ASCII subset.
    """
    # Drop backticks and `#` (Mermaid's comment char). Collapse
    # multiple spaces.
    s = s.replace("`", "'").replace("#", "no.")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _shorten_label(label: str, max_chars: int = 40) -> str:
    """Truncate long labels with an ellipsis."""
    if len(label) <= max_chars:
        return label
    return label[: max_chars - 1].rstrip() + "…"


def _node_class(node_id: str, sector: str, regime: str | None) -> str:
    """Compute the Mermaid class for a node (regime if known, else sector)."""
    if regime and regime in _REGIME_CLASSDEF:
        return f"regime_{regime.lower()}"
    if sector in _SECTOR_CLASSDEF:
        return f"sector_{sector.replace('Sector', '').lower()}"
    return "sector_default"


def _regimes_from_json(path: Path) -> dict[str, str]:
    """Load a regimes JSON file (e.g. {"data_center_shell": "PEAKED"})."""
    if not path.exists():
        _LOGGER.warning("regimes JSON missing at %s", path)
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def build_mermaid(
    chain: ValueChain,
    regimes: dict[str, str] | None = None,
) -> str:
    """Build the Mermaid source for a `flowchart LR` of the value chain.

    The output is plain Mermaid. It can be pasted into mermaid.live
    or rendered with `mmdc`.

    `regimes` is an optional {node_id: regime} map. When provided,
    nodes are colored by regime. When absent, nodes fall back to
    their sector subgraph fill.
    """
    regimes = regimes or {}
    out: list[str] = []

    # Header + init block. `base` theme gives us Mermaid's neutral
    # palette; we override classDef colors below.
    out.append("%%{init: {'theme': 'base', 'themeVariables': {'fontSize': '14px'}}}%%")
    out.append("flowchart LR")
    out.append("")

    # Group nodes by sector for the subgraph blocks. Unknown sectors
    # go in a `default` bucket.
    by_sector: dict[str, list[dict[str, Any]]] = {}
    for n in chain.nodes:
        sec = n.get("sector") or "default"
        by_sector.setdefault(sec, []).append(n)

    # Emit subgraphs in a fixed order (Materials → Hardware →
    # Infrastructure → Downstream → default) so the SVG is stable
    # run-to-run regardless of the JSON's node ordering.
    sector_order = ["MaterialsSector", "HardwareSector", "InfrastructureSector", "DownstreamSector", "default"]
    for sector in sector_order:
        nodes = by_sector.get(sector)
        if not nodes:
            continue
        out.append(f'  subgraph {sector}["{sector.replace("Sector", "")}"]')
        out.append("    direction LR")
        for n in nodes:
            node_id = n.get("id", "")
            label = _escape_label(_shorten_label(n.get("label", node_id)))
            regime = regimes.get(node_id)
            cls = _node_class(node_id, sector, regime)
            # Double-quoted label so parens and slashes are safe.
            out.append(f'    {node_id}["{label}"]:::{cls}')
        out.append("  end")
        out.append("")

    # Edges. Use a sorted set to dedupe. The chain JSON has both
    # role edges and commodity edges; we use `A -->|commodity| B` for
    # commodity edges and plain `A --> B` for role edges.
    seen_edges: set[tuple[str, str, str]] = set()
    out.append("  %% edges")
    for e in chain.edges:
        src = e.get("from")
        dst = e.get("to")
        if not src or not dst:
            continue
        commodity = e.get("commodity")
        key = (src, dst, commodity or "")
        if key in seen_edges:
            continue
        seen_edges.add(key)
        if commodity:
            commodity_label = _escape_label(commodity)
            out.append(f"  {src} -->|{commodity_label}| {dst}")
        else:
            out.append(f"  {src} --> {dst}")
    out.append("")

    # Class definitions.
    out.append("  %% classDef regime colors")
    for regime, style in _REGIME_CLASSDEF.items():
        out.append(f"  classDef regime_{regime.lower()} {style}")
    out.append("  %% classDef sector colors")
    for sector, style in _SECTOR_CLASSDEF.items():
        out.append(f"  classDef sector_{sector.replace('Sector', '').lower()} {style}")
    out.append("  classDef sector_default fill:#f3f4f6,stroke:#9ca3af,color:#374151")
    out.append("")

    return "\n".join(out)


def render_svg(mmd_path: Path, svg_path: Path, mmdc: str = "mmdc") -> bool:
    """Render .mmd to .svg using the Mermaid CLI. Returns True on success.

    Skips silently (returns False) when `mmdc` is not on PATH. The
    user is expected to `npm install -g @mermaid-js/mermaid-cli` if
    they want the SVG; the .mmd is the canonical hand-portable
    artifact.
    """
    if not shutil.which(mmdc):
        _LOGGER.warning(
            "%s not found on PATH; skipping SVG render. The .mmd is the canonical artifact. "
            "Install with: npm install -g @mermaid-js/mermaid-cli",
            mmdc,
        )
        return False
    svg_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [mmdc, "-i", str(mmd_path), "-o", str(svg_path), "-b", "white"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.CalledProcessError as e:
        _LOGGER.warning("mmdc failed: %s", e.stderr)
        return False
    except subprocess.TimeoutExpired:
        _LOGGER.warning("mmdc timed out after 60s")
        return False
    return True


def write_report_meta(svg_path: Path | None, mmd_path: Path) -> None:
    """Write a small JSON sidecar with metadata (timestamp, sizes, mmdc available)."""

    def _rel(p: Path | None) -> str | None:
        if p is None or not p.exists():
            return None
        try:
            return str(p.relative_to(_PROJECT_ROOT))
        except ValueError:
            # Path is outside the project root (e.g. inside a tmp dir).
            return str(p)

    meta = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "mmd_path": _rel(mmd_path),
        "mmd_bytes": mmd_path.stat().st_size if mmd_path.exists() else None,
        "svg_path": _rel(svg_path),
        "svg_bytes": svg_path.stat().st_size if svg_path and svg_path.exists() else None,
        "mmdc_available": shutil.which("mmdc") is not None,
    }
    meta_path = mmd_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bottlewatch-map-mermaid",
        description="Render the value chain as a Mermaid flowchart (.mmd + .svg).",
    )
    parser.add_argument(
        "--chain",
        type=Path,
        default=_DEFAULT_CHAIN,
        help="Path to value chain JSON. Default: research/00_value_chain.json.",
    )
    parser.add_argument(
        "--regimes",
        type=Path,
        default=None,
        help="Optional JSON map {node_id: regime} to color nodes.",
    )
    parser.add_argument(
        "--mmd",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR / "value-chain.mmd",
        help="Path to write the .mmd source. Default: data/cache/value-chain.mmd.",
    )
    parser.add_argument(
        "--svg",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR / "value-chain.svg",
        help="Path to write the rendered .svg. Default: data/cache/value-chain.svg.",
    )
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="Skip the mmdc SVG render step; write .mmd only.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    chain = load_chain(args.chain)
    if not chain.nodes:
        print(f"error: no nodes in {args.chain}", file=sys.stderr)
        return 1

    regimes = _regimes_from_json(args.regimes) if args.regimes else {}
    mmd_source = build_mermaid(chain, regimes)

    args.mmd.parent.mkdir(parents=True, exist_ok=True)
    args.mmd.write_text(mmd_source + "\n")
    _LOGGER.info("wrote %s (%d bytes)", args.mmd, len(mmd_source))

    svg_written = False
    if not args.no_render:
        svg_written = render_svg(args.mmd, args.svg)
        if svg_written:
            _LOGGER.info("wrote %s", args.svg)
    write_report_meta(args.svg if svg_written else None, args.mmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
