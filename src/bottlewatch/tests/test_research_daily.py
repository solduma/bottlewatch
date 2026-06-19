"""Tests for jobs/research_daily.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from unittest.mock import MagicMock, patch

from bottlewatch.app.db import ResearchSnapshot, Score, Signal, session_scope
from bottlewatch.jobs import research_daily


def _seed_score(
    session_factory: sessionmaker,
    segment: str,
    horizon: str,
    computed_at: datetime,
    score: float = 50.0,
    momentum: float = 0.0,
    regime: str = "STABLE",
    sub_scores: dict | None = None,
) -> None:
    sub_scores = sub_scores or {
        "lead_time_growth": 0.5,
        "capacity_tightness": None,
        "geo_concentration": 0.5,
        "regulatory_friction": 0.5,
        "demand_signal": 0.5,
    }
    with session_scope(session_factory) as session:
        session.add(
            Score(
                segment=segment,
                horizon=horizon,
                score=score,
                momentum=momentum,
                regime=regime,
                regime_confidence="low",
                sub_scores=sub_scores,
                data_completeness=0.8,
                first_computed_at=computed_at,
                computed_at=computed_at,
            )
        )


def test_machine_rationale_when_no_api_key(settings, factory: sessionmaker, tmp_log_path, tmp_path: Path) -> None:
    """Without an API key, the job falls back to machine-generated rationales."""
    today = datetime.now(tz=timezone.utc)
    _seed_score(factory, "advanced_node_fabs", "near", today)
    _seed_score(factory, "advanced_node_fabs", "med", today)
    _seed_score(factory, "advanced_node_fabs", "long", today)

    no_key_settings = settings.model_copy(update={"ollama_api_key": None})
    original_dir = research_daily._DAILY_OUTPUT_DIR
    research_daily._DAILY_OUTPUT_DIR = tmp_path / "daily"
    try:
        report = research_daily.run(settings=no_key_settings, factory=factory, now=today)

        assert report["total"] == 3
        assert report["llm"] == 0
        assert report["machine"] == 3

        with factory() as session:
            rows = session.execute(select(ResearchSnapshot)).scalars().all()
            assert len(rows) == 3
            for r in rows:
                assert r.generated_by == "machine"
                assert r.segment == "advanced_node_fabs"
                assert r.date == today.date()
    finally:
        research_daily._DAILY_OUTPUT_DIR = original_dir


def test_divergence_detected_when_dynamic_differs_from_seed(settings, factory: sessionmaker, tmp_path: Path) -> None:
    """A dynamic sub-score that differs from the seed by >0.2 is
    flagged in the snapshot.
    """
    today = datetime.now(tz=timezone.utc)
    seed = research_daily.load_seed()
    segment_seed: dict[str, float] = dict(seed["advanced_node_fabs"])  # type: ignore[arg-type]
    # Push lead_time_growth 0.3 away from the seed so a divergence fires.
    dynamic_lt = segment_seed["lead_time_growth"] + 0.35
    _seed_score(
        factory,
        "advanced_node_fabs",
        "near",
        today,
        sub_scores={
            "lead_time_growth": dynamic_lt,
            "capacity_tightness": None,
            "geo_concentration": segment_seed["geo_concentration"],
            "regulatory_friction": segment_seed["regulatory_friction"],
            "demand_signal": segment_seed["demand_signal"],
        },
    )

    original_dir = research_daily._DAILY_OUTPUT_DIR
    research_daily._DAILY_OUTPUT_DIR = tmp_path / "daily"
    try:
        research_daily.run(settings=settings, factory=factory, now=today)

        with factory() as session:
            row = session.execute(
                select(ResearchSnapshot).where(
                    ResearchSnapshot.segment == "advanced_node_fabs",
                    ResearchSnapshot.horizon == "near",
                )
            ).scalar_one()
            assert len(row.divergences) >= 1
            div = row.divergences[0]
            assert div["sub_score"] == "lead_time_growth"
            assert div["gap"] == pytest.approx(0.35, abs=1e-6)
    finally:
        research_daily._DAILY_OUTPUT_DIR = original_dir


def test_no_scores_today_skips_segment(settings, factory: sessionmaker, tmp_path: Path) -> None:
    """If a segment has no score rows for the snapshot date, it is skipped."""
    today = datetime.now(tz=timezone.utc)
    yesterday = today - timedelta(days=1)
    _seed_score(factory, "advanced_node_fabs", "near", yesterday)

    original_dir = research_daily._DAILY_OUTPUT_DIR
    research_daily._DAILY_OUTPUT_DIR = tmp_path / "daily"
    try:
        report = research_daily.run(settings=settings, factory=factory, now=today)
        assert report["total"] == 0
    finally:
        research_daily._DAILY_OUTPUT_DIR = original_dir


def test_signals_provided_in_context(settings, factory: sessionmaker, tmp_path: Path) -> None:
    """Recent signals for the segment are loaded and included in the prompt."""
    today = datetime.now(tz=timezone.utc)
    _seed_score(factory, "transformers_tnd", "near", today)
    with session_scope(factory) as session:
        session.add(
            Signal(
                segment="transformers_tnd",
                signal_name="ppi_transformers",
                value_num=250.0,
                unit="index",
                source="fred",
                source_id="WPU1321:2026-01",
                observed_at=today.date(),
                ingested_at=today,
            )
        )

    original_dir = research_daily._DAILY_OUTPUT_DIR
    research_daily._DAILY_OUTPUT_DIR = tmp_path / "daily"
    try:
        report = research_daily.run(settings=settings, factory=factory, now=today)
        assert report["total"] == 1
    finally:
        research_daily._DAILY_OUTPUT_DIR = original_dir


def test_artifacts_written_to_disk(settings, factory: sessionmaker, tmp_path) -> None:
    """The job writes reasoning.md and divergences.json under research/daily/."""
    today = datetime.now(tz=timezone.utc)
    _seed_score(factory, "advanced_node_fabs", "near", today)

    # Override the output directory to a temp path so the test does not
    # leave files in the repo.
    original_dir = research_daily._DAILY_OUTPUT_DIR
    research_daily._DAILY_OUTPUT_DIR = tmp_path / "daily"
    try:
        report = research_daily.run(settings=settings, factory=factory, now=today)
        out_dir = Path(report["output_dir"])
        assert out_dir.exists()
        assert (out_dir / "reasoning.md").exists()
        assert (out_dir / "divergences.json").exists()
        md = (out_dir / "reasoning.md").read_text(encoding="utf-8")
        assert "advanced_node_fabs" in md
    finally:
        research_daily._DAILY_OUTPUT_DIR = original_dir


def test_llm_called_for_interesting_segment(settings, factory: sessionmaker, tmp_path: Path) -> None:
    """When the API key is set and the segment is interesting, the
    LLM path is used.
    """
    today = datetime.now(tz=timezone.utc)
    _seed_score(factory, "advanced_node_fabs", "near", today, momentum=10.0, regime="EMERGING")

    fake_rationale = "Emerging regime because momentum is strongly positive."
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"choices": [{"message": {"content": fake_rationale}}]}

    original_dir = research_daily._DAILY_OUTPUT_DIR
    research_daily._DAILY_OUTPUT_DIR = tmp_path / "daily"
    try:
        with patch("httpx.Client") as mock_httpx:
            mock_httpx.return_value.__enter__ = MagicMock(return_value=mock_httpx.return_value)
            mock_httpx.return_value.__exit__ = MagicMock(return_value=False)
            mock_httpx.return_value.post.return_value = mock_response
            report = research_daily.run(
                settings=settings.model_copy(update={"ollama_api_key": "test-key"}),
                factory=factory,
                now=today,
                api_key="test-key",
            )

        assert report["total"] == 1
        assert report["llm"] == 1
        assert report["machine"] == 0

        with factory() as session:
            row = session.execute(select(ResearchSnapshot)).scalar_one()
            assert row.generated_by == "llm"
            assert row.rationale_md == fake_rationale
    finally:
        research_daily._DAILY_OUTPUT_DIR = original_dir


# ---------------------------------------------------------------------------
# T2.2 — numeric-claim validation (the 6 spec properties)
# ---------------------------------------------------------------------------


def _make_context(
    *,
    segment: str = "advanced_node_fabs",
    score: float = 64.8,
    momentum: float = 10.0,
    signals: list[dict] | None = None,
) -> tuple[research_daily.SegmentContext, dict]:
    """Build a SegmentContext + near score_row for validation tests."""
    seed = research_daily.load_seed()
    segment_seed = research_daily.for_segment(segment, seed)
    score_row = {
        "segment": segment,
        "horizon": "near",
        "score": score,
        "momentum": momentum,
        "regime": "EMERGING",
        "sub_scores": {
            "lead_time_growth": 0.5,
            "capacity_tightness": None,
            "geo_concentration": 0.5,
            "regulatory_friction": 0.5,
            "demand_signal": 0.5,
        },
    }
    context = research_daily.SegmentContext(
        segment=segment,
        seed=segment_seed,
        scores={"near": score_row},
        prev_scores=None,
        signals=signals or [],
        divergences=[],
    )
    return context, score_row


def test_validate_grounded_passes() -> None:
    """Property 1: a rationale citing only context numbers (incl. a rounded
    form like 65 for 64.8) has no unverified claims.
    """
    context, score_row = _make_context(score=64.8, momentum=10.0)
    rationale = "Score is 65 and momentum is 10. Geo concentration sits at 0.5."
    assert research_daily._validate_numeric_claims(rationale, context, score_row) == []


def test_validate_hallucination_flagged() -> None:
    """Property 2 (helper level): an ungrounded number is returned as unverified."""
    context, score_row = _make_context(score=64.8, momentum=10.0)
    rationale = "Lead times grew 999 weeks, an unprecedented figure."
    unverified = research_daily._validate_numeric_claims(rationale, context, score_row)
    assert 999.0 in unverified


def test_validate_no_numbers_passes() -> None:
    """Property 3: qualitative-only text never produces a false reject."""
    context, score_row = _make_context()
    rationale = "The segment remains in an emerging regime driven by demand."
    assert research_daily._validate_numeric_claims(rationale, context, score_row) == []


def test_validate_determinism() -> None:
    """Property 6: same (text, context) → same verdict."""
    context, score_row = _make_context(score=64.8)
    rationale = "Score 65, momentum 10, but exports jumped 4321."
    first = research_daily._validate_numeric_claims(rationale, context, score_row)
    second = research_daily._validate_numeric_claims(rationale, context, score_row)
    assert first == second
    assert 4321.0 in first


def test_validate_iso_dates_are_not_treated_as_numbers() -> None:
    """Regression (review #1): ISO dates must not be split into spurious
    negatives. "2026-06-15" previously parsed as 2026, -6, -15, none of which
    are grounded, wrongly rejecting any rationale that mentions a date.
    """
    context, score_row = _make_context(score=64.8, momentum=10.0)
    rationale = "As of 2026-06-15 the score is 65; the 2026-06 release confirmed momentum 10."
    assert research_daily._validate_numeric_claims(rationale, context, score_row) == []


def test_validate_percent_matches_fraction_subscore() -> None:
    """Regression (review #2): a sub-score on the 0-1 scale cited as a percent
    ("50%") must ground against its fraction form (0.50), not be rejected.
    """
    context, score_row = _make_context(score=64.8, momentum=10.0)
    # geo_concentration sub-score is 0.5 → "50%" should be accepted.
    rationale = "Geographic concentration is around 50%."
    assert research_daily._validate_numeric_claims(rationale, context, score_row) == []


def test_validate_does_not_parse_numbers_inside_identifiers() -> None:
    """Regression (review #1): digits embedded in tickers/series/codes
    ("034020.KS", "A35SNO", "co2") must not be extracted as numeric claims.
    """
    context, score_row = _make_context(score=64.8, momentum=10.0)
    rationale = "034020.KS and series A35SNO drove co2 lower; score 65."
    assert research_daily._validate_numeric_claims(rationale, context, score_row) == []


def _mock_llm_response(content: str) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def test_hallucinated_rationale_rejected(settings, factory: sessionmaker, tmp_path: Path) -> None:
    """Property 2: an LLM rationale citing a fabricated number is rejected →
    machine_rejected, and the fabricated text is NOT persisted.
    """
    today = datetime.now(tz=timezone.utc)
    _seed_score(factory, "advanced_node_fabs", "near", today, momentum=10.0, regime="EMERGING")

    fabricated = "Lead times exploded to 4321 weeks, a record high."
    original_dir = research_daily._DAILY_OUTPUT_DIR
    research_daily._DAILY_OUTPUT_DIR = tmp_path / "daily"
    try:
        with patch("httpx.Client") as mock_httpx:
            mock_httpx.return_value.__enter__ = MagicMock(return_value=mock_httpx.return_value)
            mock_httpx.return_value.__exit__ = MagicMock(return_value=False)
            mock_httpx.return_value.post.return_value = _mock_llm_response(fabricated)
            report = research_daily.run(
                settings=settings.model_copy(update={"ollama_api_key": "test-key"}),
                factory=factory,
                now=today,
                api_key="test-key",
            )

        assert report["llm"] == 0
        assert report["rejected"] == 1

        with factory() as session:
            row = session.execute(select(ResearchSnapshot)).scalar_one()
            assert row.generated_by == "machine_rejected"
            assert "4321" not in row.rationale_md
    finally:
        research_daily._DAILY_OUTPUT_DIR = original_dir


def test_llm_error_path_counted(settings, factory: sessionmaker, tmp_path: Path) -> None:
    """Property 4: when _call_llm raises, generated_by == machine_llm_error and
    the run report's llm_error count increments.
    """
    today = datetime.now(tz=timezone.utc)
    _seed_score(factory, "advanced_node_fabs", "near", today, momentum=10.0, regime="EMERGING")

    original_dir = research_daily._DAILY_OUTPUT_DIR
    research_daily._DAILY_OUTPUT_DIR = tmp_path / "daily"
    try:
        with patch.object(research_daily, "_call_llm", side_effect=RuntimeError("boom")):
            report = research_daily.run(
                settings=settings.model_copy(update={"ollama_api_key": "test-key"}),
                factory=factory,
                now=today,
                api_key="test-key",
            )

        assert report["llm_error"] == 1
        assert report["llm"] == 0

        with factory() as session:
            row = session.execute(select(ResearchSnapshot)).scalar_one()
            assert row.generated_by == "machine_llm_error"
    finally:
        research_daily._DAILY_OUTPUT_DIR = original_dir


def test_run_report_counts_partition_total(settings, factory: sessionmaker, tmp_path: Path) -> None:
    """Property 5: a run mixing happy / rejected / errored / not-interesting
    segments yields four counts that sum to total.

    Three horizons of one interesting segment: the LLM is mocked to return a
    grounded rationale, so all three pass (llm=3). We then assert the four
    counts partition total regardless.
    """
    today = datetime.now(tz=timezone.utc)
    # Interesting near horizon (momentum) + two non-interesting horizons that
    # still get a machine rationale.
    _seed_score(factory, "advanced_node_fabs", "near", today, momentum=10.0, regime="EMERGING")
    _seed_score(factory, "advanced_node_fabs", "med", today, momentum=0.0, score=50.0)
    _seed_score(factory, "advanced_node_fabs", "long", today, momentum=0.0, score=50.0)

    grounded = "Regime is emerging with strong demand."  # no numbers → passes
    original_dir = research_daily._DAILY_OUTPUT_DIR
    research_daily._DAILY_OUTPUT_DIR = tmp_path / "daily"
    try:
        with patch("httpx.Client") as mock_httpx:
            mock_httpx.return_value.__enter__ = MagicMock(return_value=mock_httpx.return_value)
            mock_httpx.return_value.__exit__ = MagicMock(return_value=False)
            mock_httpx.return_value.post.return_value = _mock_llm_response(grounded)
            report = research_daily.run(
                settings=settings.model_copy(update={"ollama_api_key": "test-key"}),
                factory=factory,
                now=today,
                api_key="test-key",
            )

        assert report["llm"] + report["machine"] + report["llm_error"] + report["rejected"] == report["total"]
        assert report["total"] == 3
    finally:
        research_daily._DAILY_OUTPUT_DIR = original_dir
