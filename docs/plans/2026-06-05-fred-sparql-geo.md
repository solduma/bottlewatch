# Plan: FRED Data Ingestion + SPARQL Geo-Concentration Extractor

## Date: 2026-06-05

## Background

The scoring pipeline (M2) has two known gaps that the user wants filled:

1. **FRED data ingestion** — the adapter exists but has stale/incorrect series IDs and a broken test.
2. **SPARQL concentration extractor** — `geo_concentration` is still hardcoded from `scoring_seed.json` (M2 stopgap). The v1 plan §10.5 calls for deriving it from the ontology via SPARQL HHI.

## Goals

1. Fix the FRED adapter series IDs to match `research/03_data_sources.md`.
2. Fix the broken `test_missing_key_is_reported_and_fetch_is_empty` test.
3. Build an ontology-driven `geo_concentration` extractor that computes HHI per segment from `operatesIn` edges.
4. Wire the extractor into the recompute job so scores reflect live ontology data.
5. All existing tests pass; new tests cover the new paths.

## HHI Methodology

From `research/04_scoring_methodology.md` §2.3:

- HHI = sum of squared market shares by region.
- Range [0, 1].
- Floor at 0.05: values < 0.05 are treated as 0 ("diversified floor").
- The ontology gives us `operatesIn` edges from role instances to `GeographicRegion` individuals.
- We proxy "market share" by equal-weighted count of role instances per region (each company's role counts as one unit of supply).

## Assumptions

- The ontology ABox (`instances.ttl`) is current and correct. If it is stale, the computed HHI will reflect stale data. Re-running `make ontology` is the operator's responsibility.
- The segment-to-role mapping in `build_ontology.py` is the canonical bridge between segment slugs and ontology role classes.
- owlready2's SPARQL engine is sufficient for the aggregation query (tested in `validate_ontology.py`).

## Hidden Assumptions / Risks

1. **Multi-region roles**: If a single role instance has multiple `operatesIn` edges, the simple count-based HHI double-counts. In practice, the builder seeds exactly one `operatesIn` per role from exchange→region mapping, so this is unlikely.
2. **Performance**: Loading the ontology + running HermiT per recompute run adds ~2-5s. The recompute job currently takes <1s. Acceptable for now; cache the world if it becomes a bottleneck.
3. **owlready2 classpath**: The reasoner shells out to a bundled JAR. On headless CI it may fail if Java is missing. The existing `validate_ontology.py` already has this risk; CI must have Java.

## Implementation Steps

### Step 1 — Fix FRED adapter series IDs

In `src/bottlewatch/app/ingest/fred.py`, update `_SERIES_SPEC` to match `research/03_data_sources.md` §4:

| Series ID | Segment | Signal Name | Unit |
|---|---|---|---|
| `INDPRO` | `general_manufacturing` | `industrial_production` | index |
| `TCU` | `general_manufacturing` | `capacity_utilization` | percent |
| `WPU31132506` | `semiconductors` | `ppi_semis` | index |
| `WPU1321` | `transformers_tnd` | `ppi_transformers` | index |

Remove `SAPPB` and `CAPUTL` (incorrect IDs) and `WPU117409` (replaced by `WPU1321`).

Keep the adapter structure unchanged — the `fetch()` loop and retry logic are fine.

**Verify:** `make test` passes (after fixture fix in Step 2).

### Step 2 — Fix `settings_no_key` test fixture

In `src/bottlewatch/tests/conftest.py`, the `settings_no_key` fixture only clears `eia_api_key`. It must also clear `fred_api_key` so the FRED "missing key" test actually sees a missing key.

```python
@pytest.fixture
def settings_no_key(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        eia_api_key=None,
        fred_api_key=None,  # <-- add
        database_url="sqlite:///:memory:",
        refresh_log_path=tmp_path / "refresh.log",
    )
```

**Verify:** `test_missing_key_is_reported_and_fetch_is_empty` passes.

### Step 3 — Add `geo_concentration` to `extractors.py`

Add two functions to `src/bottlewatch/app/score/extractors.py`:

1. `_hhi_from_counts(counts: dict[str, int]) -> float | None` — pure math.
2. `geo_concentration(segment: str, world: Any) -> float | None` — loads counts via SPARQL, delegates to `_hhi_from_counts`.

The SPARQL query:
```sparql
PREFIX : <http://bottlewatch.org/ontology#>
SELECT ?region (COUNT(?role) AS ?count) WHERE {
    ?role a :<RoleClass> .
    ?role :operatesIn ?region .
} GROUP BY ?region
```

The segment→role mapping is a new `dict` in `extractors.py` (copied from `build_ontology.py`'s `_DEFAULT_SEGMENT_TO_ROLE` for the relevant segments).

**Verify:** Unit test with a mock world object returning synthetic counts.

### Step 4 — Pass computed geo into `formula.py`

Add `geo_concentration: float | None = None` parameter to `compute_segment_score()`. When provided, it overrides the seed value. When `None`, fall back to the seed (preserving backward compat for segments without ontology roles).

```python
sub_scores = {
    ...
    "geo_concentration": geo_concentration if geo_concentration is not None else research["geo_concentration"],
    ...
}
```

**Verify:** `test_score_formula.py` still passes; add a new test `test_geo_concentration_override` that passes an explicit `geo_concentration=0.99` and asserts it overrides the seed.

### Step 5 — Wire ontology loading into recompute job

In `src/bottlewatch/jobs/recompute_scores.py`:

1. Import the ontology loading helpers (refactor `_load_ontology` from `validate_ontology.py` into a shared helper, or duplicate the small function).
2. Before the segment loop, load the world + onto once.
3. Pre-compute `geo_by_segment: dict[str, float | None]` by iterating `known_segments()` and calling `extractors.geo_concentration(seg, world)`.
4. Pass `geo_concentration=geo_by_segment.get(segment)` into `compute_segment_score()`.

**Verify:** `test_recompute_scores.py` passes. Add a new test `test_geo_concentration_computed_when_ontology_available` that seeds a minimal ontology world and asserts the score uses the computed HHI.

### Step 6 — Update tests

- `test_fred_adapter.py` — verify the fixed test passes.
- `test_score_extractors.py` — add tests for `_hhi_from_counts` and `geo_concentration` with mock world.
- `test_score_formula.py` — add override test.
- `test_recompute_scores.py` — add integration test for live HHI.

Run `make test` at the end. All must pass.

## Verification Plan

```
1. Fix FRED series IDs + fixture  → verify: make test, FRED tests green
2. Add HHI math                   → verify: new test_score_extractors passes
3. Add SPARQL query + mapping       → verify: mock-world test passes
4. Wire into formula                → verify: test_score_formula passes + override test
5. Wire into recompute job          → verify: test_recompute_scores passes + integration test
6. Full suite                       → verify: make test, coverage >= 80%
```

## Files to Touch

| File | Change |
|---|---|
| `src/bottlewatch/app/ingest/fred.py` | Update `_SERIES_SPEC` series IDs |
| `src/bottlewatch/tests/conftest.py` | Add `fred_api_key=None` to `settings_no_key` |
| `src/bottlewatch/app/score/extractors.py` | Add `_hhi_from_counts`, `geo_concentration(segment, world)` |
| `src/bottlewatch/app/score/formula.py` | Add `geo_concentration` param, use it if provided |
| `src/bottlewatch/jobs/recompute_scores.py` | Load ontology, pre-compute geo, pass to formula |
| `src/bottlewatch/tests/test_score_extractors.py` | Add HHI + geo_concentration tests |
| `src/bottlewatch/tests/test_score_formula.py` | Add override test |
| `src/bottlewatch/tests/test_recompute_scores.py` | Add integration test |

## Out of Scope

- Adding new FRED series beyond the 4 load-bearing ones (future work when demand_signal extractors land).
- Optimizing ontology load time (HermiT reasoning is already done at build time; we only need to load, not re-reason).
- Weighting HHI by `hasRoleExposure` (future v1.1 refinement).
- Handling multi-region `operatesIn` gracefully (requires ABox changes; out of scope for this pass).
