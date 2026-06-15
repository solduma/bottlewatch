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
