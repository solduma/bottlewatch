"""Validate the bottlewatch ontology with HermiT and run sample SPARQL.

Steps:
1. Load research/05_ontology/bottlewatch.owl into an owlready2 world.
2. Load research/05_ontology/instances.ttl into the same world.
3. Run the HermiT reasoner.
4. Assert no class is unsatisfiable (consistency check).
5. Assert every :Company instance has a :hasTicker.
6. Run three sample SPARQL queries from plan section 10.5.

Prints PASS/FAIL per check. Exits non-zero on any failure.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# owlready2 is imported lazily inside main() so this module can be
# imported (and type-checked) without the optional dependency installed.
owlready2: Any  # populated at runtime


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


def _print_result(result: CheckResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    line = f"[{status}] {result.name}"
    if result.detail:
        line += f"  ({result.detail})"
    print(line)


def _load_ontology(tbox_path: Path, abox_path: Path) -> tuple[Any, Any]:
    """Load both files into a fresh owlready2 world and return (world, onto)."""
    import owlready2 as _owlready2  # local import keeps the module optional

    global owlready2
    owlready2 = _owlready2

    world = _owlready2.World()
    onto = world.get_ontology(str(tbox_path.absolute().as_uri())).load()
    # Load ABox as a separate ontology so the data: prefix can be the
    # same namespace as the TBox.
    world.get_ontology(str(abox_path.absolute().as_uri())).load()
    return world, onto


def _check_class_consistency(onto: Any) -> CheckResult:
    """No class should be unsatisfiable (inferred equivalent to owl:Nothing)."""
    import owlready2 as _owlready2

    bad: list[str] = []
    for cls in onto.classes():
        if cls == _owlready2.Thing or cls == _owlready2.Nothing:
            continue
        try:
            # A class is unsatisfiable if, after reasoning, its
            # equivalent-classes set contains owl:Nothing.
            for eq in cls.equivalent_to:
                if eq == _owlready2.Nothing:
                    bad.append(cls.name)
                    break
        except Exception as e:  # noqa: BLE001 - report but don't crash
            bad.append(f"{cls.name} ({type(e).__name__})")
    if bad:
        return CheckResult("class consistency", False, f"unsatisfiable: {bad}")
    return CheckResult("class consistency", True)


def _check_companies_have_ticker(onto: Any) -> CheckResult:
    matches = onto.search(iri="http://bottlewatch.org/ontology#Company")
    if not matches:
        return CheckResult("companies have ticker", False, "no :Company class found")
    company_cls = matches[0]
    companies = list(company_cls.instances())
    missing: list[str] = []
    for c in companies:
        # Functional datatype properties in owlready2 surface as either
        # a single literal (when set) or None / empty list (when unset).
        ticker = getattr(c, "hasTicker", None)
        if not ticker:
            missing.append(c.name)
    if missing:
        return CheckResult("companies have ticker", False, f"missing ticker on: {missing[:5]}")
    return CheckResult("companies have ticker", True, f"{len(companies)} companies checked")


def _query_geo_concentration(onto: Any) -> list[tuple[str, int]]:
    """For a sample role, count distinct regions it operates in."""
    matches = onto.search(iri="http://bottlewatch.org/ontology#GPUDesigner")
    if not matches:
        return []
    instances = list(matches[0].instances())
    rows: list[tuple[str, int]] = []
    for inst in instances:
        regions_attr = getattr(inst, "operatesIn", None) or []
        regions = {r.name for r in regions_attr}
        rows.append((inst.name, len(regions)))
    rows.sort()
    return rows


def _query_supply_path_depth(world: Any) -> list[tuple[str, int]]:
    """For each value-chain node, find upstream hop count to GPU designers.

    We walk the SPARQL property path :supplies* forward (GPU-designers
    are at the leaves; we start from every node in the chain and
    measure how many supplies-edges we cross to reach a GPU designer).

    owlready2's SPARQL parser is a reduced SPARQL 1.0 + a small set of
    property-path extensions, so we use the vanilla path syntax that
    round-trips: it expresses "every node reachable by zero-or-more
    :supplies edges ending at a GPU designer" - which is what the
    value-chain map's edges mean (supplier -> buyer).
    """
    query = """
    PREFIX : <http://bottlewatch.org/ontology#>
    SELECT ?role (COUNT(?mid) AS ?hops) WHERE {
        ?role :supplies* ?mid .
        ?mid a :GPUDesigner .
        FILTER(?role != ?mid)
    } GROUP BY ?role
    ORDER BY ?hops
    """
    res = list(world.sparql(query))
    rows: list[tuple[str, int]] = []
    for row in res:
        if len(row) < 2:
            continue
        role = row[0]
        hops = row[1]
        role_name = role.split("#")[-1] if isinstance(role, str) else getattr(role, "name", str(role))
        try:
            hops_int = int(hops)
        except (TypeError, ValueError):
            hops_int = 0
        rows.append((role_name, hops_int))
    return rows


def _query_nvda_role_competitors(world: Any) -> list[str]:
    """List companies that share NVDA's role CLASS (any :Role they play).

    The per-company role individuals in the ABox (NVDA_GPUDesignerRole,
    AMD_GPUDesignerRole, ...) are distinct individuals - they don't share
    a role node. The shared entity is the CLASS (:GPUDesigner). So the
    correct SPARQL joins on rdf:type, not on the role individual, and
    uses the HermiT-inferred subclass closure to also pick up
    :NetworkingSiliconDesigner / :ASICDesigner role-mates of NVDA.
    """
    query = """
    PREFIX : <http://bottlewatch.org/ontology#>
    PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
    SELECT DISTINCT ?competitor WHERE {
        ?nvda :hasTicker "NVDA" .
        ?nvda :playsRole ?myRole .
        ?competitor :playsRole ?theirRole .
        ?myRole a ?roleClass .
        ?theirRole a ?roleClass .
        FILTER(?competitor != ?nvda)
    }
    """
    res = list(world.sparql(query))
    names: list[str] = []
    for row in res:
        if not row:
            continue
        comp = row[0]
        name = comp.split("#")[-1] if isinstance(comp, str) else getattr(comp, "name", str(comp))
        names.append(name)
    return sorted(set(names))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the bottlewatch ontology")
    parser.add_argument(
        "--tbox",
        type=Path,
        default=Path("research/05_ontology/bottlewatch.owl"),
    )
    parser.add_argument(
        "--abox",
        type=Path,
        default=Path("research/05_ontology/instances.ttl"),
    )
    args = parser.parse_args(argv)

    if not args.tbox.exists():
        print(f"error: TBox not found at {args.tbox}", file=sys.stderr)
        return 2
    if not args.abox.exists():
        print(f"error: ABox not found at {args.abox}", file=sys.stderr)
        return 2

    print(f"loading {args.tbox} and {args.abox} ...")
    world, onto = _load_ontology(args.tbox, args.abox)

    print("running HermiT reasoner ...")
    try:
        # owlready2's reasoner API is module-level, not on World. The
        # sync_reasoner_hermit() helper (a) writes the loaded ontologies
        # to a temp RDF/XML, (b) shells out to the bundled HermiT jar,
        # (c) reads the inferred axioms back into the world. We pass
        # infer_property_values=True so any future sub-property chains
        # (e.g. hasRoleExposure o playsRole -> hasAggregateExposure) come
        # back populated.
        with world:
            owlready2.sync_reasoner_hermit(
                x=onto,
                infer_property_values=True,
                debug=1,
            )
    except Exception as e:  # noqa: BLE001 - report but don't crash
        print(f"  reasoner raised {type(e).__name__}: {e}", file=sys.stderr)
        _print_result(CheckResult("reasoner", False, str(e)))
        return 1
    _print_result(CheckResult("reasoner", True))

    results: list[CheckResult] = [
        _check_class_consistency(onto),
        _check_companies_have_ticker(onto),
    ]
    for r in results:
        _print_result(r)

    # Sample SPARQL queries (informational; don't fail on empty results
    # because the ABox may be sparse during early M0).
    print()
    print("--- sample SPARQL: geo_concentration (GPUDesigner roles) ---")
    geo = _query_geo_concentration(onto)
    if not geo:
        print("  (no GPUDesigner instances)")
    for role_name, n in geo[:10]:
        print(f"  {role_name}: {n} region(s)")

    print()
    print("--- sample SPARQL: supply_path_depth (upstream of GPUDesigner) ---")
    depth_rows = _query_supply_path_depth(world)
    if not depth_rows:
        print("  (no upstream roles found)")
    for role_name, depth in depth_rows[:10]:
        print(f"  {role_name}: depth {depth}")

    print()
    print("--- sample SPARQL: NVDA role-mates (competitors) ---")
    competitors = _query_nvda_role_competitors(world)
    if not competitors:
        print("  (no role-mates for NVDA)")
    for name in competitors:
        print(f"  {name}")

    if all(r.passed for r in results):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
