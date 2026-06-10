"""Tests for the build_ontology job."""

from __future__ import annotations

import json
from rdflib import Graph, Namespace

from bottlewatch.jobs import build_ontology

BW = Namespace("http://bottlewatch.org/ontology#")


def test_build_ontology_happy_path(tmp_path):
    # Setup dummy universe CSV
    universe_csv = tmp_path / "universe.csv"
    universe_csv.write_text(
        "ticker,exchange,name,segment,subsegment,exposure_pct,market_cap_bucket,mcap_usd,currency_hedge,notes\n"
        "NVDA,NASDAQ,Nvidia,fabless,gpu,100,Large,1000000000000,,none\n"
        "TSM,TWSE,TSMC,foundry,advanced,100,Large,500000000000,,none\n"
    )

    # Setup dummy value chain JSON
    chain_json = tmp_path / "chain.json"
    chain_json.write_text(
        json.dumps(
            {
                "nodes": [
                    {"id": "advanced_node_fabs", "label": "Fabs", "role_kind": "Foundry"},
                    {"id": "gpu_asic_silicon", "label": "GPU", "role_kind": "GPUDesigner"},
                ],
                "edges": [{"from": "advanced_node_fabs", "to": "gpu_asic_silicon", "role_kind": "supplies"}],
            }
        )
    )

    out_ttl = tmp_path / "instances.ttl"

    stats = build_ontology.build(universe_csv, chain_json, out_ttl)

    assert stats.companies == 2
    assert stats.roles == 2
    assert stats.supply_edges == 1
    assert out_ttl.exists()

    # Verify content via rdflib
    g = Graph()
    g.parse(str(out_ttl), format="nt")

    # Check NVDA exists as a company
    assert (BW.NVDA, None, None) in g  # This is wrong, should check RDF.type
    # Correct check:
    from rdflib.namespace import RDF

    assert (BW.NVDA, RDF.type, BW.Company) in g
    assert (BW.TSM, RDF.type, BW.Company) in g

    # Check the supply edge
    # Nodes in value chain are VCNode_...
    assert (BW.VCNode_advanced_node_fabs, BW.supplies, BW.VCNode_gpu_asic_silicon) in g


def test_build_ontology_skips_placeholders(tmp_path):
    universe_csv = tmp_path / "universe.csv"
    universe_csv.write_text(
        "ticker,exchange,name,segment,subsegment,exposure_pct,market_cap_bucket,mcap_usd,currency_hedge,notes\n"
        "TICK,NASDAQ,Name,segment,REMOVE_ME,100,Large,1000000000,none,none\n"
        "ZERO,NASDAQ,Name,segment,valid,0,Large,1000000000,none,none\n"
    )
    chain_json = tmp_path / "chain.json"
    chain_json.write_text(json.dumps({"nodes": [], "edges": []}))
    out_ttl = tmp_path / "instances.ttl"

    stats = build_ontology.build(universe_csv, chain_json, out_ttl)
    assert stats.companies == 0
    assert len(stats.skipped_rows) == 2
