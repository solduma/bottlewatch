"""GET /api/v1/map.

JSON-only stub of the value chain DAG. Returns the parsed
`research/00_value_chain.json` with each node annotated with
the current near-horizon regime (if the node id matches a known
segment slug in the `scores` table).

M3 will add a React Flow frontend that consumes this payload.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import Score, Thesis


_LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["map"])

# Project root: src/bottlewatch/app/api/map.py -> 4 levels up
_CHAIN_JSON = Path(__file__).resolve().parents[4] / "research" / "00_value_chain.json"


@router.get("/map")
def get_map(request: Request) -> dict[str, Any]:
    factory: sessionmaker = request.app.state.session_factory

    if not _CHAIN_JSON.exists():
        _LOGGER.warning("value chain JSON not found at %s", _CHAIN_JSON)
        return {"nodes": [], "edges": []}

    with _CHAIN_JSON.open(encoding="utf-8") as fh:
        chain = json.load(fh)

    # Build a {segment: regime} index for the near horizon. Some
    # node ids (e.g. "raw_inputs", "fuel_power_inputs") don't map to
    # scoring segments — those get regime = None.
    with factory() as session:
        score_rows = session.execute(
            select(Score.segment, Score.regime, Score.score, Score.momentum).where(Score.horizon == "near")
        ).all()
    regimes = {
        seg: {"regime": regime, "score": score, "momentum": momentum} for seg, regime, score, momentum in score_rows
    }

    nodes = []
    for n in chain.get("nodes", []):
        node_id = n.get("id", "")
        # Some node ids are like "advanced_node_fabs" — match directly.
        # Others like "raw_oil_gas" don't have a scoring segment.
        node_regime = regimes.get(node_id, {})
        nodes.append(
            {
                "id": node_id,
                "label": n.get("label", node_id),
                "sector": n.get("sector", ""),
                "regime": node_regime.get("regime"),
                "score": node_regime.get("score"),
                "momentum": node_regime.get("momentum"),
                "companies": n.get("companies", []),
            }
        )

    return {"nodes": nodes, "edges": chain.get("edges", [])}


# ---------------------------------------------------------------------------
# Node detail (GET /v1/map/{slug})
# BFS traversal of upstream + downstream from a node.
# Depth limited to 3. Cycles broken by visited set.
# ---------------------------------------------------------------------------

_MAX_DEPTH = 3

# Lazy-loaded value chain graph (nodes + edges dicts).
_chain_graph: dict | None = None


def _load_chain_graph() -> dict:
    global _chain_graph
    if _chain_graph is not None:
        return _chain_graph
    if not _CHAIN_JSON.exists():
        _LOGGER.warning("value chain JSON not found at %s", _CHAIN_JSON)
        return {"nodes": [], "edges": []}
    with _CHAIN_JSON.open(encoding="utf-8") as fh:
        _chain_graph = json.load(fh)
    return _chain_graph


def _build_adjacency() -> tuple[dict[str, list[str]], dict[str, dict]]:
    """Build (out_edges, node_lookup) from the value chain graph.

    `out_edges[n]` = list of node ids that `n` supplies (forward direction).
    `node_lookup[n]` = node dict.
    """
    chain = _load_chain_graph()
    out_edges: dict[str, list[str]] = {n["id"]: [] for n in chain.get("nodes", [])}
    node_lookup: dict[str, dict] = {n["id"]: n for n in chain.get("nodes", [])}
    for edge in chain.get("edges", []):
        src = edge.get("source")
        tgt = edge.get("target")
        if src and tgt and src in out_edges:
            out_edges[src].append(tgt)
    return out_edges, node_lookup


def _bfs_path(
    start: str,
    direction: str,
    out_edges: dict[str, list[str]],
    node_lookup: dict[str, dict],
    regimes: dict,
) -> list[dict]:
    """BFS from `start` in `direction` (upstream=reverse, downstream=forward).

    Returns list of {id, regime, score, depth} dicts, depth 1.._MAX_DEPTH.
    """
    if start not in node_lookup:
        return []

    # Reverse edges for upstream.
    in_edges: dict[str, list[str]] = {n: [] for n in node_lookup}
    for src, tgts in out_edges.items():
        for tgt in tgts:
            in_edges.setdefault(tgt, []).append(src)

    edges_to_follow = out_edges if direction == "downstream" else in_edges
    results: list[dict] = []
    visited: set[str] = {start}
    frontier = [(start, 1)]

    while frontier:
        current, depth = frontier.pop(0)
        if depth >= _MAX_DEPTH:
            break
        for neighbor in edges_to_follow.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            reg_info = regimes.get(neighbor, {})
            results.append(
                {
                    "id": neighbor,
                    "regime": reg_info.get("regime"),
                    "score": reg_info.get("score"),
                    "depth": depth,
                }
            )
            frontier.append((neighbor, depth + 1))

    return sorted(results, key=lambda x: x["depth"])


def _node_exists(slug: str) -> bool:
    chain = _load_chain_graph()
    return any(n["id"] == slug for n in chain.get("nodes", []))


@router.get("/map/{slug}")
def get_map_node(request: Request, slug: str) -> dict:
    factory = request.app.state.session_factory

    # Build regime index for all near-horizon scores.
    with factory() as session:
        score_rows = session.execute(
            select(Score.segment, Score.regime, Score.score, Score.momentum).where(Score.horizon == "near")
        ).all()
    regimes = {
        seg: {"regime": regime, "score": score, "momentum": momentum} for seg, regime, score, momentum in score_rows
    }

    # Load the value chain.
    if not _node_exists(slug):
        from fastapi import HTTPException as _HE

        raise _HE(status_code=404, detail=f"map node not found: {slug!r}")

    out_edges, node_lookup = _build_adjacency()
    node_dict = node_lookup[slug]

    upstream = _bfs_path(slug, "upstream", out_edges, node_lookup, regimes)
    downstream = _bfs_path(slug, "downstream", out_edges, node_lookup, regimes)

    # Companies for this node.
    companies = node_dict.get("companies", [])

    # ETA from the static table (only for scoring segments).
    eta = None
    if slug in regimes:
        from bottlewatch.app.api.eta import _STATIC_ETA

        if slug in _STATIC_ETA:
            eta_band, conf = _STATIC_ETA[slug]
            eta = {"eta": eta_band, "confidence": conf}

    # Thesis count for this node's segment.
    thesis_count = 0
    if slug in regimes:  # only score-bearing segments have thesis
        with factory() as session:
            cnt = session.execute(select(func.count(Thesis.id)).where(Thesis.segment == slug)).scalar()
            thesis_count = int(cnt) if cnt else 0

    return {
        "node": {
            "id": slug,
            "label": node_dict.get("label", slug),
            "sector": node_dict.get("sector", ""),
            "regime": regimes.get(slug, {}).get("regime"),
            "score": regimes.get(slug, {}).get("score"),
            "momentum": regimes.get(slug, {}).get("momentum"),
        },
        "upstream": upstream,
        "downstream": downstream,
        "companies": companies,
        "eta": eta,
        "thesis_count": thesis_count,
    }
