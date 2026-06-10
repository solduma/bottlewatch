"""Tests for the validate_ontology job."""

from __future__ import annotations

import pytest
from bottlewatch.jobs import validate_ontology


def test_validate_ontology_missing_files(tmp_path):
    assert (
        validate_ontology.main(
            [
                "--tbox",
                str(tmp_path / "missing.owl"),
                "--abox",
                str(tmp_path / "missing.ttl"),
            ]
        )
        == 2
    )


def test_validate_ontology_happy_path(tmp_path):
    # Minimal TBox mirroring research/05_ontology/bottlewatch.owl:
    #   - `xml:base` + `owl:Ontology` declaration so the loader registers
    #     classes under `http://bottlewatch.org/ontology#` (otherwise
    #     `onto.search(iri=...)` would not find them).
    #   - `:supplies` declared as TransitiveProperty with domain/range so
    #     SPARQL property-path queries (`?role :supplies* ?mid`) can
    #     resolve it. Without the TransitiveProperty type, owlready2's
    #     strict SPARQL parser raises "No existing entity for IRI".
    #   - `:playsRole` and `:operatesIn` declared so the
    #     `_query_nvda_role_competitors` and `_query_geo_concentration`
    #     sample SPARQLs can parse.
    tbox = tmp_path / "test.owl"
    tbox.write_text(
        '<?xml version="1.0"?>\n'
        '<rdf:RDF xml:base="http://bottlewatch.org/ontology" '
        'xmlns="http://bottlewatch.org/ontology#" '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#" '
        'xmlns:owl="http://www.w3.org/2002/07/owl#">\n'
        '  <owl:Ontology rdf:about="http://bottlewatch.org/ontology"/>\n'
        '  <owl:Class rdf:about="#Company"/>\n'
        '  <owl:Class rdf:about="#Role"/>\n'
        '  <owl:Class rdf:about="#GPUDesigner"><rdf:type rdf:resource="#Role"/></owl:Class>\n'
        '  <owl:ObjectProperty rdf:about="#supplies">\n'
        '    <rdf:type rdf:resource="http://www.w3.org/2002/07/owl#TransitiveProperty"/>\n'
        '    <rdfs:domain rdf:resource="#Role"/>\n'
        '    <rdfs:range rdf:resource="#Role"/>\n'
        "  </owl:ObjectProperty>\n"
        '  <owl:ObjectProperty rdf:about="#playsRole">\n'
        '    <rdfs:domain rdf:resource="#Company"/>\n'
        '    <rdfs:range rdf:resource="#Role"/>\n'
        "  </owl:ObjectProperty>\n"
        '  <owl:ObjectProperty rdf:about="#operatesIn"/>\n'
        '  <owl:DatatypeProperty rdf:about="#hasTicker"/>\n'
        "</rdf:RDF>"
    )
    abox = tmp_path / "test.ttl"
    abox.write_text(
        "<http://bottlewatch.org/ontology#NVDA> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://bottlewatch.org/ontology#Company> .\n"
        '<http://bottlewatch.org/ontology#NVDA> <http://bottlewatch.org/ontology#hasTicker> "NVDA" .\n'
    )

    try:
        res = validate_ontology.main(
            [
                "--tbox",
                str(tbox),
                "--abox",
                str(abox),
            ]
        )
        assert res == 0
    except ImportError:
        pytest.skip("owlready2 not installed")
