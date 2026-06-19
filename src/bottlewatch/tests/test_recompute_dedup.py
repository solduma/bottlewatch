"""Tests for the dedup logic in `recompute_scores._load_signals_by_segment`.

The dedup applies to sources in `_IDEMPOTENT_SOURCES` (currently
`eia_860m`). For these, re-ingesting the same planned addition
emits a new row with a new `ingested_at` but the same
`(source, source_id, observed_at)` — `observed_at` is the planned
operation date, which is invariant across ingestion runs.

Dedup contract: for an idempotent source, exactly one row is
returned per `(segment, signal_name, source_id)`, and that row
is the one with the latest `ingested_at`. For non-idempotent
sources, every row is preserved (each row is a distinct
time-series point).

These tests use the in-memory SQLite fixture and call
`_load_signals_by_segment` directly so the test exercises the
real SQL path, not a mocked equivalent.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import Signal, session_scope
from bottlewatch.jobs.recompute_scores import _load_signals_by_segment


# Window that covers all fixtures below. `_load_signals_by_segment`
# filters `observed_at BETWEEN since AND until`, so all fixture
# dates are placed well inside.
_SINCE = datetime(2025, 1, 1, tzinfo=timezone.utc)
_UNTIL = datetime(2027, 12, 31, tzinfo=timezone.utc)


def _insert(
    factory: sessionmaker, *, source: str, source_id: str, value: float, observed_at: date, ingested_at: datetime
) -> None:
    """Insert one Signal row directly. Bypasses the orchestrator's
    no-dedup policy so we can set `ingested_at` per row.
    """
    with session_scope(factory) as session:
        session.add(
            Signal(
                segment="power_generation_oem",
                subsegment=None,
                signal_name="planned_capacity_mw",
                value_num=value,
                unit="MW",
                source=source,
                source_id=source_id,
                observed_at=observed_at,
                ingested_at=ingested_at,
            )
        )


def test_idempotent_source_n_ingestions_same_observed_at_keeps_latest(factory: sessionmaker) -> None:
    """Spec property 1: a planned addition ingested 3 times (same
    `observed_at`, increasing `ingested_at`) yields exactly 1 row,
    the one with max `ingested_at`. The chosen row's `value_num`
    matches the most recently ingested value (1000.0).
    """
    # All three rows: same (segment, signal_name, source_id, observed_at).
    # Distinct `ingested_at` and `value_num` so we can identify the
    # "winner" by either field.
    _insert(
        factory,
        source="eia_860m",
        source_id="p1",
        value=900.0,
        observed_at=date(2026, 3, 1),
        ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    _insert(
        factory,
        source="eia_860m",
        source_id="p1",
        value=1000.0,
        observed_at=date(2026, 3, 1),
        ingested_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )
    _insert(
        factory,
        source="eia_860m",
        source_id="p1",
        value=950.0,
        observed_at=date(2026, 3, 1),
        ingested_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    out = _load_signals_by_segment(factory, since=_SINCE, until=_UNTIL)
    rows = out.get("power_generation_oem", [])
    planned = [r for r in rows if r.signal_name == "planned_capacity_mw"]

    assert len(planned) == 1, f"expected 1 deduped row, got {len(planned)}: {planned}"
    assert planned[0].value_num == 1000.0, (
        f"expected the row with latest ingested_at (value=1000.0), got {planned[0].value_num}"
    )


def test_idempotent_source_single_ingestion_returned_unchanged(factory: sessionmaker) -> None:
    """Spec property 2: a single ingestion is returned as-is (no
    regression on the common case where there's no duplicate).
    """
    _insert(
        factory,
        source="eia_860m",
        source_id="p2",
        value=500.0,
        observed_at=date(2026, 6, 1),
        ingested_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )

    out = _load_signals_by_segment(factory, since=_SINCE, until=_UNTIL)
    rows = out.get("power_generation_oem", [])
    planned = [r for r in rows if r.signal_name == "planned_capacity_mw"]

    assert len(planned) == 1
    assert planned[0].value_num == 500.0


def test_non_idempotent_source_preserves_all_rows(factory: sessionmaker) -> None:
    """Spec property 3: FRED (not in _IDEMPOTENT_SOURCES) is a
    time-series source; every row is a distinct observation. None
    of them should be deduped.
    """
    # 3 FRED rows for the same source_id at different observed_at.
    # This models a monthly ppi_transformers series: each row is a
    # distinct data point and all 3 must be returned.
    for i, val in enumerate([100.0, 110.0, 120.0]):
        _insert(
            factory,
            source="fred",
            source_id="ppi_x",
            value=val,
            observed_at=date(2026, 1, 1) + timedelta(days=30 * i),
            ingested_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )

    out = _load_signals_by_segment(factory, since=_SINCE, until=_UNTIL)
    rows = out.get("power_generation_oem", [])
    fred_rows = [r for r in rows if r.signal_name == "planned_capacity_mw" and r.value_num in (100.0, 110.0, 120.0)]
    # Note: FRED's real signal_name is ppi_transformers; we use
    # planned_capacity_mw here only because the dedup dispatches
    # on `source`, not `signal_name`. The point is that the FRED
    # rows are not deduped.
    assert len(fred_rows) == 3, f"expected 3 FRED rows preserved, got {len(fred_rows)}"


def test_idempotent_source_mix_of_single_and_multi_source_ids(factory: sessionmaker) -> None:
    """Spec property 4: with 2 source_ids, one single-ingestion and
    one triple-ingestion, the result is exactly 2 rows — one per
    source_id, each at its latest `ingested_at`.
    """
    # source_id="alpha": single ingestion.
    _insert(
        factory,
        source="eia_860m",
        source_id="alpha",
        value=1.0,
        observed_at=date(2026, 1, 1),
        ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    # source_id="beta": 3 ingestions, values 2, 3, 4. Latest wins (4).
    _insert(
        factory,
        source="eia_860m",
        source_id="beta",
        value=2.0,
        observed_at=date(2026, 2, 1),
        ingested_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    _insert(
        factory,
        source="eia_860m",
        source_id="beta",
        value=4.0,
        observed_at=date(2026, 2, 1),
        ingested_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )
    _insert(
        factory,
        source="eia_860m",
        source_id="beta",
        value=3.0,
        observed_at=date(2026, 2, 1),
        ingested_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    out = _load_signals_by_segment(factory, since=_SINCE, until=_UNTIL)
    rows = out.get("power_generation_oem", [])
    planned = sorted(
        (r for r in rows if r.signal_name == "planned_capacity_mw"),
        key=lambda r: r.value_num or 0.0,
    )

    assert len(planned) == 2, f"expected 2 deduped rows, got {len(planned)}"
    by_value = {r.value_num: r for r in planned}
    assert by_value[1.0].value_num == 1.0, "alpha (single) should be present at its only value"
    assert by_value[4.0].value_num == 4.0, "beta (3 ingestions) should be present at its latest value"
