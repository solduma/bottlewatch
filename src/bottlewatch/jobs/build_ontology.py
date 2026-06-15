"""Generate the bottlewatch ABox (instances.ttl) from the universe CSV
and the value chain JSON.

Inputs:
- research/02_universe.csv  (ticker, exchange, name, segment, subsegment,
  exposure_pct, market_cap_bucket, mcap_usd, currency_hedge, notes)
- research/00_value_chain.json (DAG: nodes with id, label, sector,
  companies[]; edges with from, to, commodity?, role_kind?)

Output:
- research/05_ontology/instances.ttl

Idempotent: re-running overwrites the file deterministically.

Tolerant of upstream format drift:
- The default segment-to-role map below covers the v1 universe taxonomy.
  For an unknown segment we still emit a role individual typed as the
  generic :Role (so the build never fails on a new segment string).
- Rows whose subsegment starts with "REMOVE" or whose exposure is 0 are
  skipped to filter the placeholder/instrument rows the research agent
  sometimes leaves in the CSV.
- The value chain JSON's `role_kind` selects the object property; edges
  without `role_kind` default to :supplies.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import rdflib
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from bottlewatch.app.score.geo import _EXCHANGE_TO_REGION

# Namespace: ontology is the default prefix; individuals share it.
BW = Namespace("http://bottlewatch.org/ontology#")

# Sizing thresholds per the plan: drop sub-$2B names for v1.
_LARGE_MID_CAP_THRESHOLD_USD = 2_000_000_000

# Tolerant default mapping: CSV `segment` value -> ontology role class.
# Anything not in this map is emitted as the generic :Role and logged.
_DEFAULT_SEGMENT_TO_ROLE: dict[str, str] = {
    # Original v1 set (preserved for backward-compat tests)
    "foundry": "Foundry",
    "idm": "IDM",
    "fabless": "FablessDesigner",
    "fabless_gpu": "GPUDesigner",
    "fabless_networking": "NetworkingSiliconDesigner",
    "fabless_asic": "ASICDesigner",
    "osat": "OSAT",
    "equipment": "EquipmentMaker",
    "materials": "MaterialsSupplier",
    "power_oem": "PowerEquipmentOEM",
    "electrical_equipment": "ElectricalEquipmentMaker",
    "utility": "Utility",
    "idc": "IDCOperator",
    "idc_self_build": "SelfBuildIDCOperator",
    "water_utility": "WaterUtility",
    "system_oem": "SystemOEM",
    "odm": "ODM",
    "rack_integrator": "RackIntegrator",
    "hyperscaler": "Hyperscaler",
    "neocloud": "Neocloud",
    "enterprise_saas": "EnterpriseSaaSConsumer",
    # Parallel research agent's richer taxonomy (see /research/02_universe.csv).
    # Fabless subsegments map to the FINE-GRAINED fabless subclasses
    # (GPUDesigner / NetworkingSiliconDesigner / ASICDesigner) so the
    # reasoner can recover them via rdf:type without needing per-row
    # subclass assertions. The TBox's class hierarchy propagates up to
    # :FablessDesigner, so any SPARQL query for FablessDesigner continues
    # to match all of them.
    "advanced_node_fabs": "Foundry",
    "hbm_memory": "IDM",
    "gpu_asic_silicon": "GPUDesigner",
    "networking_interconnect": "NetworkingSiliconDesigner",
    "front_end_equipment": "EquipmentMaker",
    "advanced_packaging": "OSAT",
    "power_generation_oem": "PowerEquipmentOEM",
    "transformers_tnd": "ElectricalEquipmentMaker",
    "data_center_shell": "IDCOperator",
    "cooling_water": "ElectricalEquipmentMaker",
    "systems_rack_scale": "RackIntegrator",
}

# Map the value chain's `role_kind` field to the right object property.
_ROLE_KIND_TO_PROPERTY: dict[str, URIRef] = {
    "supplies": BW.supplies,
    "suppliesCommodity": BW.suppliesCommodity,
    "dependsOnCommodity": BW.dependsOnCommodity,
}


@dataclass
class BuildStats:
    """Counters printed at the end of a successful build."""

    companies: int = 0
    roles: int = 0
    supply_edges: int = 0
    plays_role_edges: int = 0
    operates_in_edges: int = 0
    depends_on_commodity_edges: int = 0
    supplies_commodity_edges: int = 0
    role_exposure_edges: int = 0
    generic_roles_emitted: list[str] = field(default_factory=list)
    skipped_rows: list[tuple[int, str]] = field(default_factory=list)


def _local_name(value: str) -> str:
    """Sanitize an arbitrary string into a safe Turtle local name.

    Replaces runs of non-alphanumerics with a single underscore and strips
    leading/trailing underscores. Empty inputs fall back to `anon`.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return cleaned or "anon"


def _make_company_uri(ticker: str) -> URIRef:
    return BW[_local_name(ticker)]


def _make_role_uri(ticker: str, role_label: str) -> URIRef:
    return BW[f"{_local_name(ticker)}_{_local_name(role_label)}Role"]


def _make_role_node_uri(node_id: str) -> URIRef:
    """Role-URI used by the value chain graph.

    The value chain map is segment-oriented (e.g. node id "advanced_fabs")
    rather than ticker-oriented, so we mint a separate role individual per
    DAG node and link to it from company-side roles via `supplies`.
    """
    return BW[f"VCNode_{_local_name(node_id)}"]


def _required_columns(headers: list[str] | None, required: set[str], source: Path) -> None:
    if headers is None:
        raise ValueError(f"{source} has no header row")
    missing = required - set(headers)
    if missing:
        raise ValueError(f"{source} is missing required columns: {sorted(missing)}")


def _coerce_decimal(raw: str | None) -> Decimal | None:
    if raw is None or raw == "":
        return None
    cleaned = raw.replace(",", "").replace("$", "").strip()
    try:
        return Decimal(cleaned)
    except Exception as e:  # noqa: BLE001 - report raw value for the user
        raise ValueError(f"cannot parse decimal {raw!r}") from e


def _load_universe_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        _required_columns(
            list(reader.fieldnames) if reader.fieldnames is not None else None,
            {
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
            },
            path,
        )
        return list(reader)


def _load_value_chain(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"nodes": [], "edges": []}
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or "nodes" not in data or "edges" not in data:
        raise ValueError(f"{path} must be a JSON object with 'nodes' and 'edges' arrays")
    return data


def _is_skip_row(row: dict[str, str]) -> bool:
    """Return True for placeholder rows the research agent leaves in."""
    subsegment = (row.get("subsegment") or "").strip().lower()
    if subsegment.startswith("remove") or subsegment == "placeholder":
        return True
    exposure = _coerce_decimal(row.get("exposure_pct"))
    if exposure is not None and exposure <= 0:
        return True
    return False


def _add_company(graph: Graph, row: dict[str, str], stats: BuildStats) -> URIRef:
    """Emit a `:Company` individual with the standard datatype slots."""
    ticker = row["ticker"].strip()
    if not ticker:
        raise ValueError("universe CSV row has empty ticker")

    company = _make_company_uri(ticker)
    graph.add((company, RDF.type, BW.Company))
    graph.add((company, BW.hasTicker, Literal(ticker, datatype=XSD.string)))
    graph.add((company, BW.hasExchange, Literal(row["exchange"].strip(), datatype=XSD.string)))
    graph.add(
        (
            company,
            BW.hasCurrency,
            Literal(_currency_for_exchange(row["exchange"]), datatype=XSD.string),
        )
    )
    mcap = _coerce_decimal(row.get("mcap_usd"))
    if mcap is not None and mcap > 0:
        graph.add((company, BW.hasMarketCap, Literal(mcap, datatype=XSD.decimal)))
        graph.add(
            (
                company,
                BW.isLargeOrMidCap,
                Literal(mcap >= _LARGE_MID_CAP_THRESHOLD_USD, datatype=XSD.boolean),
            )
        )
    hedge = (row.get("currency_hedge") or "").strip()
    if hedge:
        graph.add((company, BW.hasCurrencyHedge, Literal(hedge, datatype=XSD.string)))
    graph.add((company, BW.isPublic, Literal(True, datatype=XSD.boolean)))
    # Legacy Company-level exposure: keep the row's value (0-100) for any
    # query that hasn't migrated to per-role. v1 retains this for back-compat.
    exposure = _coerce_decimal(row.get("exposure_pct"))
    if exposure is not None:
        graph.add((company, BW.hasExposurePct, Literal(exposure, datatype=XSD.decimal)))
    stats.companies += 1
    return company


def _currency_for_exchange(exchange: str) -> str:
    code = (exchange or "").strip().upper()
    if code in {"NYSE", "NASDAQ", "NYSEMKT", "AMEX", "OTCQX", "OTHER"}:
        return "USD"
    if code in {"TSE", "TYO"}:
        return "JPY"
    if code in {"KRX", "KOSPI"}:
        return "KRW"
    if code in {"TWSE"}:
        return "TWD"
    if code in {"FRA", "XETRA", "ETR", "EPA", "BME", "OSLO"}:
        return "EUR"
    if code in {"LSE"}:
        return "GBP"
    if code in {"HKEX"}:
        return "HKD"
    if code in {"SSE", "SZSE"}:
        return "CNY"
    if code in {"SGX"}:
        return "SGD"
    if code in {"TADAWUL"}:
        return "SAR"
    return "USD"


def _add_role_for_row(
    graph: Graph,
    row: dict[str, str],
    company: URIRef,
    segment_map: dict[str, str],
    stats: BuildStats,
) -> URIRef | None:
    """Emit a per-(company, role) individual typed with the role class.

    Unknown segment values fall back to the generic :Role so the build
    never fails on a new segment string. The fallback is logged in
    stats.generic_roles_emitted for human review.
    """
    segment_key = (row.get("segment") or "").strip().lower()
    role_label = segment_map.get(segment_key)

    if role_label is not None:
        role = _make_role_uri(row["ticker"], role_label)
        graph.add((role, RDF.type, BW[role_label]))
    else:
        role = _make_role_uri(row["ticker"], segment_key or "Generic")
        graph.add((role, RDF.type, BW.Role))
        stats.generic_roles_emitted.append(f"{row['ticker']}/{segment_key}")

    graph.add((company, BW.playsRole, role))
    stats.plays_role_edges += 1

    # REIFIED per-(company, role) exposure. The CSV's exposure_pct is the
    # share of THIS role in the company's revenue, not a single
    # company-wide figure. A conglomerate like TSMC can thus carry
    # 90% Foundry + 10% OSAT in two reified slots rather than one number
    # swallowing the other. Convention: 0-100 (matches CSV and plan §2.3).
    exposure = _coerce_decimal(row.get("exposure_pct"))
    if exposure is not None:
        graph.add((role, BW.hasRoleExposure, Literal(exposure, datatype=XSD.decimal)))
        stats.role_exposure_edges += 1

    # Default geographic hint: roll the exchange up to a region.
    exchange = (row.get("exchange") or "").strip().upper()
    region = _EXCHANGE_TO_REGION.get(exchange)
    if region is not None:
        graph.add((role, BW.operatesIn, BW[region]))
        stats.operates_in_edges += 1

    stats.roles += 1
    return role


def _add_value_chain(graph: Graph, chain: dict[str, Any], stats: BuildStats) -> dict[str, URIRef]:
    """Emit the value-chain role individuals and `supplies` edges.

    Honors the `role_kind` field on each edge (supplies / suppliesCommodity
    / dependsOnCommodity). Returns a map of node id -> role URI for any
    cross-referencing the caller wants to do.
    """
    node_index: dict[str, URIRef] = {}
    for node in chain.get("nodes", []):
        if not isinstance(node, dict) or "id" not in node:
            continue
        node_uri = _make_role_node_uri(node["id"])
        node_index[node["id"]] = node_uri
        # Type the VC node with a role class. Honor an explicit `role_kind`
        # on the node, otherwise fall back to the segment map so that
        # `gpu_asic_silicon` -> :GPUDesigner, `advanced_packaging` -> :OSAT,
        # etc. The HermiT reasoner will then be able to answer queries
        # like "what does :GPUDesigner depend on upstream?" by walking
        # the (typed) supplies edges.
        node_id = node["id"]
        role_kind = node.get("role_kind")
        if not (isinstance(role_kind, str) and role_kind):
            role_kind = _DEFAULT_SEGMENT_TO_ROLE.get(node_id)
        if isinstance(role_kind, str) and role_kind:
            graph.add((node_uri, RDF.type, BW[_local_name(role_kind)]))

    for edge in chain.get("edges", []):
        if not isinstance(edge, dict):
            continue
        from_, to = edge.get("from"), edge.get("to")
        if not isinstance(from_, str) or not isinstance(to, str):
            continue
        src = node_index.get(from_)
        dst = node_index.get(to)
        if src is None or dst is None:
            continue
        role_kind = edge.get("role_kind") or "supplies"
        commodity_name = edge.get("commodity")
        commodity_uri = BW[_local_name(commodity_name)] if isinstance(commodity_name, str) and commodity_name else None

        if role_kind == "supplies":
            graph.add((src, BW.supplies, dst))
            stats.supply_edges += 1
        elif role_kind == "suppliesCommodity":
            # A supplier role ships a commodity to the destination role.
            # The graph-level edge is :supplies; the commodity link is
            # :suppliesCommodity from the supplier.
            graph.add((src, BW.supplies, dst))
            stats.supply_edges += 1
            if commodity_uri is not None:
                graph.add((src, BW.suppliesCommodity, commodity_uri))
                stats.supplies_commodity_edges += 1
        elif role_kind == "dependsOnCommodity" and commodity_uri is not None:
            graph.add((src, BW.dependsOnCommodity, commodity_uri))
            stats.depends_on_commodity_edges += 1

    return node_index


def build(
    csv_path: Path,
    chain_path: Path,
    out_path: Path,
    segment_map: dict[str, str] | None = None,
) -> BuildStats:
    """Build instances.ttl and return stats.

    `segment_map` overrides the default segment-to-role mapping. Pass an
    empty dict to disable the mapping entirely (every role will be a
    generic :Role).

    The same ticker can appear on multiple rows (e.g. ADR + local
    listing, or a placeholder row next to a real one). We deduplicate:
    the first non-skipped row emits the `:Company`; subsequent rows
    only emit additional `:Role` individuals and link them via
    `:playsRole`. The exchange/currency of the company record reflects
    the first row seen.
    """
    segment_map = segment_map if segment_map is not None else _DEFAULT_SEGMENT_TO_ROLE
    rows = _load_universe_csv(csv_path)
    chain = _load_value_chain(chain_path)

    graph = Graph()
    graph.bind("", BW)
    graph.bind("owl", rdflib.OWL)
    graph.bind("rdf", RDF)
    graph.bind("xsd", XSD)

    stats = BuildStats()
    company_index: dict[str, URIRef] = {}

    for idx, row in enumerate(rows, start=2):  # 1-based + header
        ticker = (row.get("ticker") or "").strip()
        if not ticker:
            stats.skipped_rows.append((idx, "empty ticker"))
            continue
        if _is_skip_row(row):
            stats.skipped_rows.append((idx, "placeholder / 0-exposure row"))
            continue
        try:
            company = company_index.get(ticker)
            if company is None:
                company = _add_company(graph, row, stats)
                company_index[ticker] = company
            _add_role_for_row(graph, row, company, segment_map, stats)
        except Exception as e:  # noqa: BLE001 - log and continue
            stats.skipped_rows.append((idx, f"{type(e).__name__}: {e}"))

    _add_value_chain(graph, chain, stats)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Output as NTriples, not Turtle: the validator (validate_ontology.py)
    # loads the file through owlready2, whose default N-Triples parser
    # cannot ingest Turtle. NTriples is verbose but unambiguous and lets
    # us re-use the same file for both human inspection and reasoner
    # loading. (A `make instances.ttl.turtle` follow-up step is cheap if
    # we ever want a pretty-printed copy for the docs.)
    graph.serialize(destination=str(out_path), format="nt")
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build bottlewatch instances.ttl")
    parser.add_argument(
        "--universe",
        type=Path,
        default=Path("research/02_universe.csv"),
        help="Path to the universe CSV.",
    )
    parser.add_argument(
        "--value-chain",
        type=Path,
        default=Path("research/00_value_chain.json"),
        help="Path to the value chain JSON DAG.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("research/05_ontology/instances.ttl"),
        help="Output Turtle path.",
    )
    args = parser.parse_args(argv)

    try:
        stats = build(args.universe, args.value_chain, args.out)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(f"wrote {args.out}")
    print(f"  companies:               {stats.companies}")
    print(f"  roles:                   {stats.roles}")
    print(f"  playsRole edges:         {stats.plays_role_edges}")
    print(f"  operatesIn edges:        {stats.operates_in_edges}")
    print(f"  supplies edges:          {stats.supply_edges}")
    print(f"  suppliesCommodity edges: {stats.supplies_commodity_edges}")
    print(f"  dependsOnCommodity:      {stats.depends_on_commodity_edges}")
    print(f"  hasRoleExposure edges:   {stats.role_exposure_edges}")
    if stats.generic_roles_emitted:
        print(
            f"  generic (unmapped) roles: {len(stats.generic_roles_emitted)} "
            f"(examples: {', '.join(stats.generic_roles_emitted[:5])})"
        )
    if stats.skipped_rows:
        print(f"  skipped rows:            {len(stats.skipped_rows)}")
        for line, reason in stats.skipped_rows[:5]:
            print(f"    line {line}: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
