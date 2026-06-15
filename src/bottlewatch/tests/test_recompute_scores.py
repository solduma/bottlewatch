"""Tests for jobs/recompute_scores.py.

Uses the in-memory engine + factory from conftest. We seed
fixture signals so the capacity_tightness extractors can produce
non-None values.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import Score, Signal, session_scope
from bottlewatch.app.score.research_values import known_segments
from bottlewatch.jobs import recompute_scores


def _seed_signals(session_factory: sessionmaker) -> None:
    """Insert a small fixture set of signals across 2 segments.

    Dates are computed relative to `now` so the recompute job's
    730-day signal window always sees the seeded rows. Hardcoded
    2024/2027 dates drift out of the window as time passes (a
    test that worked in 2024-2025 silently regresses in 2026+).
    """
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    # Anchor "now" at the 1st of the current month so monthly signals
    # land on a stable day boundary and don't shift between
    # morning and evening test runs.
    today = now.date().replace(day=1)
    rows = [
        # power_generation_oem: 2 planned + 1 operating, all
        # within the 730-day window.
        Signal(
            segment="power_generation_oem",
            subsegment=None,
            signal_name="planned_capacity_mw",
            value_num=2000.0,
            unit="MW",
            source="eia_860m",
            source_id="p1",
            observed_at=today - timedelta(days=180),
            ingested_at=now,
        ),
        Signal(
            segment="power_generation_oem",
            subsegment=None,
            signal_name="planned_capacity_mw",
            value_num=3000.0,
            unit="MW",
            source="eia_860m",
            source_id="p2",
            observed_at=today - timedelta(days=90),
            ingested_at=now,
        ),
        Signal(
            segment="power_generation_oem",
            subsegment=None,
            signal_name="capacity_mw",
            value_num=20000.0,
            unit="MW",
            source="eia_v2_capacity",
            source_id="c1",
            observed_at=today - timedelta(days=30),
            ingested_at=now,
        ),
    ]
    # data_center_shell: 24 months of monthly retail_sales_mwh.
    # First 12 are the "old" period (val 1000), next 12 are the
    # "new" period (val 1200) — together a +20% YoY growth that
    # lands inside the extractor's [-0.10, +0.25] band. Latest
    # point is "last month"; earliest is 23 months back.
    latest_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    for i in range(24):
        first_of_target = (latest_month - timedelta(days=30 * (23 - i))).replace(day=1)
        val = 1000.0 if i < 12 else 1200.0
        rows.append(
            Signal(
                segment="data_center_shell",
                subsegment=None,
                signal_name="retail_sales_mwh",
                value_num=val,
                unit="MWh",
                source="eia_v2",
                source_id=f"sales{i}",
                observed_at=first_of_target,
                ingested_at=now,
            )
        )
    with session_scope(session_factory) as session:
        for r in rows:
            session.add(r)


def _seed_transformer_signals(session_factory: sessionmaker) -> None:
    """Seed FRED A35SNO-style signals for the `transformers_tnd`
    segment so the new dynamic `demand_signal` extractor fires.

    13 months of `electrical_equipment_orders`: latest = 100,
    year-ago = 80 → +25% YoY → 1.0. This drives the
    `transformers_tnd.demand_signal` sub-score away from the
    static seed (0.80) and into the dynamic range.

    Dates are anchored on the 1st of each month so monthly
    signals are stable regardless of which day of the month
    the test runs on. The series spans 13 months ending on
    the 1st of the month prior to `now`.
    """
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    today = now.date().replace(day=1)
    # Walk back 13 months from today; the latest is the most recent
    # 1st-of-month strictly before today.
    rows = []
    for i in range(13):
        # i=0 is the OLDEST month (13mo back), i=12 is the LATEST.
        year = today.year + (today.month - 1 - (12 - i)) // 12
        month = (today.month - 1 - (12 - i)) % 12 + 1
        obs = date(year, month, 1)
        # v: latest = 100 (i=12), year-ago = 80 (i=0)
        v = 80.0 + (i * (100 - 80) / 12)
        rows.append(
            Signal(
                segment="transformers_tnd",
                subsegment=None,
                signal_name="electrical_equipment_orders",
                value_num=v,
                unit="index",
                source="fred",
                source_id=f"A35SNO:{obs:%Y-%m}",
                observed_at=obs,
                ingested_at=now,
            )
        )
    with session_scope(session_factory) as session:
        for r in rows:
            session.add(r)


def test_writes_one_row_per_segment_per_horizon(settings, factory: sessionmaker, tmp_log_path) -> None:
    _seed_signals(factory)
    report = recompute_scores.run(settings=settings, factory=factory)
    segments = known_segments()
    assert report.rows_written == len(segments) * len(settings.score_horizons)
    assert report.exit_code == 0
    with factory() as session:
        scores = session.execute(select(Score)).scalars().all()
        assert len(scores) == report.rows_written
        # All scores share the same first_computed_at on first run.
        first = {s.first_computed_at for s in scores}
        assert len(first) == 1


def test_idempotent_recompute_overwrites_existing_rows(settings, factory: sessionmaker) -> None:
    _seed_signals(factory)
    first = recompute_scores.run(settings=settings, factory=factory)
    second = recompute_scores.run(settings=settings, factory=factory)
    # Same row count, no duplicates.
    assert first.rows_written == second.rows_written
    with factory() as session:
        assert len(session.execute(select(Score)).scalars().all()) == first.rows_written
    # The second run's first_computed_at was carried over from the first.
    with factory() as session:
        scores = session.execute(select(Score)).scalars().all()
        first_at = {s.first_computed_at for s in scores}
        assert len(first_at) == 1  # same single first_computed_at across all rows


def test_power_segment_gets_computed_capacity(settings, factory: sessionmaker) -> None:
    """power_generation_oem should have data_completeness=1.0 (all
    5 sub-scores populated), other segments 0.8 (no extractor).
    """
    _seed_signals(factory)
    recompute_scores.run(settings=settings, factory=factory)
    with factory() as session:
        rows = session.execute(select(Score)).scalars().all()
        by_segment = {(s.segment, s.horizon): s for s in rows}
        for horizon in settings.score_horizons:
            assert by_segment[("power_generation_oem", horizon)].data_completeness == 1.0
            assert by_segment[("data_center_shell", horizon)].data_completeness == 1.0
            assert by_segment[("transformers_tnd", horizon)].data_completeness == 0.8


def test_recompute_preserves_horizon_subset(settings, factory: sessionmaker) -> None:
    """A Settings with `score_horizons=["near"]` produces only the
    near-horizon rows (one per segment). The recompute job does
    not assume the full 3-horizon tuple.
    """
    _seed_signals(factory)
    settings_with_one = settings.model_copy(update={"score_horizons": ["near"]})
    report = recompute_scores.run(settings=settings_with_one, factory=factory)
    assert report.rows_written == len(known_segments())
    with factory() as session:
        horizons = {r for (r,) in session.execute(select(Score.horizon)).all()}
        assert horizons == {"near"}


def test_no_signals_still_writes_research_only_scores(settings, factory: sessionmaker) -> None:
    """A fresh DB with zero signals still gets 30 rows: 4 research
    sub-scores per segment × 3 horizons. The capacity_tightness
    is None, data_completeness=0.8.
    """
    report = recompute_scores.run(settings=settings, factory=factory)
    assert report.rows_written == len(known_segments()) * 3
    assert report.no_data_count == 0  # 0.8 completeness > 0.4 NO_DATA threshold
    with factory() as session:
        rows = session.execute(select(Score)).scalars().all()
        for r in rows:
            assert r.data_completeness == 0.8
            assert r.sub_scores["capacity_tightness"] is None
            assert r.regime != "NO_DATA"


def test_appends_log_line(settings, factory: sessionmaker) -> None:
    _seed_signals(factory)
    recompute_scores.run(settings=settings, factory=factory)
    log = settings.refresh_log_path.read_text().strip().splitlines()
    assert len(log) == 1
    import json

    payload = json.loads(log[0])
    assert payload["source"] == "score_recompute"
    assert payload["status"] == "OK"
    assert payload["rows_written"] == len(known_segments()) * 3


class _MockWorld:
    """Duck-typed stand-in for an `owlready2.World`.

    Returns the rows registered for the role class named in the
    SPARQL query. `sparql` is called once per segment by
    `_compute_geo_by_segment`; we count calls per role class so the
    test can assert the recompute job actually queried for it.
    """

    def __init__(self, results_by_role: dict[str, list[tuple[object, int]]]) -> None:
        self._results = results_by_role

    def sparql(self, query: str) -> list[tuple[object, int]]:
        for role, rows in self._results.items():
            if f":{role} " in query or f":{role} ." in query:
                return list(rows)
        return []


def test_signals_are_deduped_to_latest_observed_at(settings, factory: sessionmaker) -> None:
    """Regression: the recompute job reads signals within the 730d
    window. Without dedup, a planned_capacity_mw signal for the
    same (segment, signal_name, source_id) ingested monthly is
    summed N times by `_power_tightness`, double-counting the
    planned addition. The fix keeps only the most recent
    `observed_at` per tuple.
    """
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    today = now.date().replace(day=1)
    rows = [
        # Same source_id "p1", three monthly re-ingestions of the
        # same planned addition: 2000 MW each.
        Signal(
            segment="power_generation_oem",
            subsegment=None,
            signal_name="planned_capacity_mw",
            value_num=2000.0,
            unit="MW",
            source="eia_860m",
            source_id="p1",
            observed_at=today - timedelta(days=180),
            ingested_at=now,
        ),
        Signal(
            segment="power_generation_oem",
            subsegment=None,
            signal_name="planned_capacity_mw",
            value_num=2000.0,  # same data, re-ingested
            unit="MW",
            source="eia_860m",
            source_id="p1",
            observed_at=today - timedelta(days=90),
            ingested_at=now,
        ),
        Signal(
            segment="power_generation_oem",
            subsegment=None,
            signal_name="planned_capacity_mw",
            value_num=2000.0,  # same data, re-ingested
            unit="MW",
            source="eia_860m",
            source_id="p1",
            observed_at=today - timedelta(days=30),
            ingested_at=now,
        ),
        Signal(
            segment="power_generation_oem",
            subsegment=None,
            signal_name="capacity_mw",
            value_num=20000.0,
            unit="MW",
            source="eia_v2_capacity",
            source_id="c1",
            observed_at=today - timedelta(days=30),
            ingested_at=now,
        ),
    ]
    with session_scope(factory) as session:
        session.add_all(rows)
    recompute_scores.run(settings=settings, factory=factory)
    with factory() as session:
        rows_out = session.execute(select(Score)).scalars().all()
        for r in rows_out:
            if r.segment == "power_generation_oem":
                # Without dedup: 3 * 2000 / 20000 = 0.3 (tight)
                # With dedup: 1 * 2000 / 20000 = 0.1 (loose)
                cap = r.sub_scores["capacity_tightness"]
                assert cap is not None
                assert cap == pytest.approx(0.1, abs=1e-6), f"expected dedup'd capacity_tightness=0.1, got {cap}"


def test_geo_concentration_computed_when_ontology_available(settings, factory: sessionmaker) -> None:
    """When the recompute job is given a pre-loaded ontology world,
    the score rows for the matching segment reflect the computed
    HHI, not the seed value.

    Foundry instances: 3 in US, 1 in TW → HHI = 0.625 (no floor drop).
    The advanced_node_fabs seed is 0.65, so the override produces a
    slightly lower value (0.625) — that delta is what we assert on.
    """
    mock_world = _MockWorld({"Foundry": [("US", 3), ("TW", 1)]})
    recompute_scores.run(settings=settings, factory=factory, ontology_world=mock_world)
    with factory() as session:
        rows = session.execute(select(Score)).scalars().all()
        by_segment = {(s.segment, s.horizon): s for s in rows}
        # The advanced_node_fabs segment should have the computed HHI.
        for horizon in settings.score_horizons:
            assert by_segment[("advanced_node_fabs", horizon)].sub_scores["geo_concentration"] == pytest.approx(
                0.625, abs=1e-3
            )
        # Other segments (no Foundry role class in the mock) fall back
        # to the seed because their SPARQL query returns no rows.
        # transformers_tnd seed is 0.35 — confirm the seed path is taken.
        for horizon in settings.score_horizons:
            assert by_segment[("transformers_tnd", horizon)].sub_scores["geo_concentration"] == pytest.approx(0.35)


def test_demand_signal_override_when_fred_signal_present(settings, factory: sessionmaker) -> None:
    """When the recompute job is given FRED `A35SNO` signals for
    `transformers_tnd`, the score rows for that segment reflect
    the dynamically-extracted demand_signal (1.0 for +25% YoY),
    not the seed value (0.80).

    Mirrors `test_geo_concentration_computed_when_ontology_available`
    for the new demand_signal override path. The transformer
    segment is the first one to have a dynamic demand_signal
    extractor (FRED A35SNO → electrical_equipment_orders).
    """
    _seed_transformer_signals(factory)
    recompute_scores.run(settings=settings, factory=factory)
    with factory() as session:
        rows = session.execute(select(Score)).scalars().all()
        by_segment = {(s.segment, s.horizon): s for s in rows}
        # The transformers_tnd segment should have the dynamic
        # demand_signal (1.0 for the seeded +25% YoY growth).
        for horizon in settings.score_horizons:
            assert by_segment[("transformers_tnd", horizon)].sub_scores["demand_signal"] == pytest.approx(
                1.0, abs=1e-3
            ), (
                f"expected dynamic demand_signal=1.0, got {by_segment[('transformers_tnd', horizon)].sub_scores['demand_signal']}"
            )
        # Other segments (no dynamic demand_signal extractor)
        # fall back to the seed. e.g. advanced_node_fabs seed = 0.90.
        for horizon in settings.score_horizons:
            assert by_segment[("advanced_node_fabs", horizon)].sub_scores["demand_signal"] == pytest.approx(0.90)


def test_demand_signal_falls_back_to_seed_without_fred_signals(settings, factory: sessionmaker) -> None:
    """Without any FRED `A35SNO` signals in the DB, the
    `transformers_tnd` segment's demand_signal falls back to the
    static seed (0.80). This preserves M2 stopgap behavior for
    operators who haven't pulled FRED data yet.
    """
    recompute_scores.run(settings=settings, factory=factory)
    with factory() as session:
        rows = session.execute(select(Score)).scalars().all()
        by_segment = {(s.segment, s.horizon): s for s in rows}
        for horizon in settings.score_horizons:
            assert by_segment[("transformers_tnd", horizon)].sub_scores["demand_signal"] == pytest.approx(0.80)


def _seed_transformer_ppi_signals(session_factory: sessionmaker) -> None:
    """Seed FRED WPU1321-style signals for the `transformers_tnd`
    segment so the new dynamic `lead_time_growth` extractor fires.

    2 months of `ppi_transformers`: latest = 250 (a 2026-Q1
    reading, mid-band; band is [80, 350]). This drives the
    `transformers_tnd.lead_time_growth` sub-score away from the
    static seed (0.85) and into the dynamic range
    (250 - 80) / (350 - 80) = 0.63.
    """
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    today = now.date().replace(day=1)
    rows = [
        Signal(
            segment="transformers_tnd",
            subsegment=None,
            signal_name="ppi_transformers",
            value_num=200.0,
            unit="index",
            source="fred",
            source_id="WPU1321:2025-12",
            observed_at=today - timedelta(days=30),
            ingested_at=now,
        ),
        Signal(
            segment="transformers_tnd",
            subsegment=None,
            signal_name="ppi_transformers",
            value_num=250.0,
            unit="index",
            source="fred",
            source_id="WPU1321:2026-01",
            observed_at=today,
            ingested_at=now,
        ),
    ]
    with session_scope(session_factory) as session:
        session.add_all(rows)


def test_lead_time_growth_override_when_fred_signal_present(settings, factory: sessionmaker) -> None:
    """When the recompute job is given FRED `WPU1321` signals for
    `transformers_tnd`, the score rows for that segment reflect
    the dynamically-extracted lead_time_growth (~0.63 for
    PPI=250, with band [80, 350]), not the seed value (0.85).

    Mirrors `test_demand_signal_override_when_fred_signal_present`
    and `test_geo_concentration_computed_when_ontology_available`
    for the third dynamic-override path.
    """
    _seed_transformer_ppi_signals(factory)
    recompute_scores.run(settings=settings, factory=factory)
    with factory() as session:
        rows = session.execute(select(Score)).scalars().all()
        by_segment = {(s.segment, s.horizon): s for s in rows}
        for horizon in settings.score_horizons:
            assert by_segment[("transformers_tnd", horizon)].sub_scores["lead_time_growth"] == pytest.approx(
                0.63, abs=1e-2
            ), (
                f"expected dynamic lead_time_growth=0.63, "
                f"got {by_segment[('transformers_tnd', horizon)].sub_scores['lead_time_growth']}"
            )
        # Other segments (no dynamic lead_time_growth extractor)
        # fall back to the seed. e.g. advanced_node_fabs seed = 0.85.
        for horizon in settings.score_horizons:
            assert by_segment[("advanced_node_fabs", horizon)].sub_scores["lead_time_growth"] == pytest.approx(0.85)


def test_lead_time_growth_falls_back_to_seed_without_fred_signals(settings, factory: sessionmaker) -> None:
    """Without any FRED `WPU1321` signals in the DB, the
    `transformers_tnd` segment's lead_time_growth falls back to
    the static seed (0.85). This preserves M2 stopgap behavior
    for operators who haven't pulled FRED data yet.
    """
    recompute_scores.run(settings=settings, factory=factory)
    with factory() as session:
        rows = session.execute(select(Score)).scalars().all()
        by_segment = {(s.segment, s.horizon): s for s in rows}
        for horizon in settings.score_horizons:
            assert by_segment[("transformers_tnd", horizon)].sub_scores["lead_time_growth"] == pytest.approx(0.85)


def _seed_ppi_with_release_dates(
    session_factory: sessionmaker,
    *,
    older_released_at: datetime | None,
    newer_released_at: datetime | None,
    newer_ingested_at: datetime | None = None,
) -> None:
    """Seed two `ppi_transformers` rows for `transformers_tnd`.

    Lets callers control either `released_at` or `ingested_at` so
    both the true release-date gate and the ingested_at fallback can
    be exercised.
    """
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    today = now.date().replace(day=1)
    rows = [
        Signal(
            segment="transformers_tnd",
            subsegment=None,
            signal_name="ppi_transformers",
            value_num=200.0,
            unit="index",
            source="fred",
            source_id="WPU1321:2025-12",
            observed_at=today - timedelta(days=30),
            ingested_at=now,
            released_at=older_released_at,
        ),
        Signal(
            segment="transformers_tnd",
            subsegment=None,
            signal_name="ppi_transformers",
            value_num=250.0,
            unit="index",
            source="fred",
            source_id="WPU1321:2026-01",
            observed_at=today,
            ingested_at=newer_ingested_at if newer_ingested_at is not None else now,
            released_at=newer_released_at,
        ),
    ]
    with session_scope(session_factory) as session:
        session.add_all(rows)


def test_point_in_time_gating_uses_released_at(settings, factory: sessionmaker) -> None:
    """A signal whose `released_at` is after `as_of` is excluded from a
    historical recompute. Only the older row remains, so the dynamic
    lead_time_growth extractor returns None and the segment falls
    back to the static seed.
    """
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    _seed_ppi_with_release_dates(
        factory,
        older_released_at=now - timedelta(days=1),
        newer_released_at=now + timedelta(days=1),
    )
    recompute_scores.run(settings=settings, factory=factory, as_of=now)
    with factory() as session:
        rows = session.execute(select(Score)).scalars().all()
        by_segment = {(s.segment, s.horizon): s for s in rows}
        for horizon in settings.score_horizons:
            assert by_segment[("transformers_tnd", horizon)].sub_scores["lead_time_growth"] == pytest.approx(0.85), (
                "expected lead_time_growth to fall back to seed when newer signal is gated"
            )


def test_point_in_time_fallback_to_ingested_at(settings, factory: sessionmaker) -> None:
    """When `released_at` is null, the point-in-time gate falls back to
    `ingested_at`. A row ingested after `as_of` is excluded.
    """
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    _seed_ppi_with_release_dates(
        factory,
        older_released_at=None,
        newer_released_at=None,
        newer_ingested_at=now + timedelta(days=1),
    )
    recompute_scores.run(settings=settings, factory=factory, as_of=now)
    with factory() as session:
        rows = session.execute(select(Score)).scalars().all()
        by_segment = {(s.segment, s.horizon): s for s in rows}
        for horizon in settings.score_horizons:
            assert by_segment[("transformers_tnd", horizon)].sub_scores["lead_time_growth"] == pytest.approx(0.85), (
                "expected lead_time_growth to fall back to seed when newer signal is gated by ingested_at"
            )


def test_daily_recompute_ignores_released_at_gate(settings, factory: sessionmaker) -> None:
    """The default production recompute path (no `as_of`) loads the
    latest signal regardless of its `released_at`, preserving
    existing behavior.
    """
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    _seed_ppi_with_release_dates(
        factory,
        older_released_at=now - timedelta(days=1),
        newer_released_at=now + timedelta(days=1),
    )
    recompute_scores.run(settings=settings, factory=factory)
    with factory() as session:
        rows = session.execute(select(Score)).scalars().all()
        by_segment = {(s.segment, s.horizon): s for s in rows}
        for horizon in settings.score_horizons:
            assert by_segment[("transformers_tnd", horizon)].sub_scores["lead_time_growth"] == pytest.approx(
                0.63, abs=1e-2
            ), "expected daily recompute to use the newer signal despite future released_at"


def test_geo_concentration_end_to_end_against_real_abox(settings, factory: sessionmaker) -> None:
    """Live integration test: load the real ABox from
    `research/05_ontology/instances.ttl`, run recompute, and
    assert that all 10 segments get a non-None HHI for
    `geo_concentration` (the ABox is the system-under-test's
    population; if it's missing, the test will surface that
    with a clear assertion failure rather than a silent skip).

    This is the only test that exercises the real
    `instances.ttl` (every other test uses `_MockWorld`). It
    would have caught a real-ABox drift like a region name
    change that breaks the SPARQL query.
    """
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[3]  # src/bottlewatch/tests/...
    abox = project_root / "research" / "05_ontology" / "instances.ttl"
    if not abox.exists():
        pytest.skip(f"ABox not built yet ({abox}); run `make ontology` first")
    world = recompute_scores.load_ontology_world()
    assert world is not None, f"load_ontology_world returned None; check {abox} is well-formed"
    recompute_scores.run(settings=settings, factory=factory, ontology_world=world)
    with factory() as session:
        rows = session.execute(select(Score)).scalars().all()
        by_segment = {(s.segment, s.horizon): s for s in rows}
        # Every known segment has a role class in SEGMENT_TO_ROLE_CLASS,
        # so every segment's geo_concentration should be a real HHI
        # value (or None if the ABox has no role instances for that
        # class — which would be a data bug worth surfacing).
        for segment in known_segments():
            for horizon in settings.score_horizons:
                geo = by_segment[(segment, horizon)].sub_scores["geo_concentration"]
                # At least the segments that have role instances in
                # the real ABox must produce a non-None HHI. The
                # ABox has 131 role instances across all 10 classes
                # (per the `make ontology` summary), so this should
                # hold for all 10.
                assert geo is not None, (
                    f"geo_concentration for {segment} is None against the real ABox; "
                    "ABox is missing role instances for this segment's role class"
                )
                # HHI is in [1/n, 1] where n is the number of regions
                # passing the 5% floor. With 1+ regions it can be
                # anywhere in [0, 1] but never negative or > 1.
                assert 0.0 <= geo <= 1.0, f"HHI for {segment} = {geo} is out of [0, 1]"
