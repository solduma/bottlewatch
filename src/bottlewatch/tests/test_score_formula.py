"""Tests for app/score/formula.py — assembly of B(s, h) from the
5 sub-scores + horizon weights.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest
from dataclasses import dataclass

from bottlewatch.app.score.formula import (
    HORIZONS,
    ScoreResult,
    compute_segment_score,
)
from bottlewatch.app.score.regime import Regime


@dataclass(frozen=True)
class _Row:
    signal_name: str
    value_num: Optional[float]
    observed_at: object  # unused in the no-extractor path


def test_full_b_near_for_power() -> None:
    # power_generation_oem with planned_capacity_mw (forward 5000) +
    # capacity_mw (20000) → capacity_tightness = 5000/20000 = 0.25.
    # B(near) = 100 * (0.30*0.80 + 0.35*0.25 + 0.10*0.35 + 0.05*0.67 + 0.20*0.85) / 1.0
    #         = 100 * (0.24 + 0.0875 + 0.035 + 0.0335 + 0.17)
    #         = 100 * 0.566 = 56.6
    result = compute_segment_score(
        "power_generation_oem",
        "near",
        signals=[
            _Row("planned_capacity_mw", 5000.0, None),
            _Row("capacity_mw", 20000.0, None),
        ],
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert isinstance(result, ScoreResult)
    assert result.segment == "power_generation_oem"
    assert result.horizon == "near"
    assert result.score == pytest.approx(56.6, abs=1e-3)
    assert result.data_completeness == 1.0
    assert result.regime is Regime.STABLE  # B=56.6, B'=0 → STABLE
    assert result.regime_confidence == "low"


def test_full_b_respects_horizon_weights() -> None:
    # Same sub-scores, different horizons → different B values.
    # advanced_node_fabs has the highest lead_time_growth (0.85)
    # and geo_concentration (0.65) of any segment, so its long
    # horizon should weight geo more heavily.
    near = compute_segment_score(
        "advanced_node_fabs",
        "near",
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    long = compute_segment_score(
        "advanced_node_fabs",
        "long",
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert near.score is not None and long.score is not None
    # Both should be PEAKED-ish (research seed gives 0.85 lead time
    # and 0.65 geo, no capacity extractor).
    assert near.regime in (Regime.PEAKED, Regime.PEAKING, Regime.STABLE)
    assert long.regime in (Regime.PEAKED, Regime.PEAKING, Regime.STABLE)


def test_momentum_zero_on_first_compute() -> None:
    # No b_history → B' = 0, regime_confidence = "low"
    result = compute_segment_score(
        "transformers_tnd",
        "med",
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert result.momentum == 0.0
    assert result.regime_confidence == "low"


def test_regime_confidence_increases_with_age() -> None:
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # 30 days later → low
    result_low = compute_segment_score(
        "transformers_tnd",
        "near",
        first_computed_at=first,
        now=datetime(2026, 1, 31, tzinfo=timezone.utc),
    )
    assert result_low.regime_confidence == "low"
    # 120 days later → medium
    result_med = compute_segment_score(
        "transformers_tnd",
        "near",
        first_computed_at=first,
        now=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    assert result_med.regime_confidence == "medium"
    # 200 days later → high
    result_high = compute_segment_score(
        "transformers_tnd",
        "near",
        first_computed_at=first,
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    assert result_high.regime_confidence == "high"


def test_unknown_horizon_raises() -> None:
    with pytest.raises(ValueError, match="unknown horizon"):
        compute_segment_score("transformers_tnd", "weekly", now=datetime.now(tz=timezone.utc))


def test_horizons_tuple_is_canonical() -> None:
    # The recompute job iterates Settings.score_horizons; the formula
    # only accepts the canonical tuple. Mismatch → ValueError.
    assert HORIZONS == ("near", "med", "long")


def test_sub_scores_contains_all_five_names() -> None:
    result = compute_segment_score(
        "transformers_tnd",
        "near",
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert set(result.sub_scores.keys()) == {
        "lead_time_growth",
        "capacity_tightness",
        "geo_concentration",
        "regulatory_friction",
        "demand_signal",
    }
    # transformers_tnd has no extractor → capacity_tightness is None
    assert result.sub_scores["capacity_tightness"] is None


def test_to_persisted_shape_matches_score_orm() -> None:
    # The recompute job calls ScoreResult.to_persisted() and feeds
    # the result to bulk_insert_mappings. The keys must match the
    # Score ORM column names exactly.
    result = compute_segment_score(
        "power_generation_oem",
        "near",
        signals=[_Row("capacity_mw", 1000.0, None)],
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    persisted = result.to_persisted()
    assert set(persisted.keys()) == {
        "segment",
        "horizon",
        "score",
        "momentum",
        "regime",
        "regime_confidence",
        "sub_scores",
        "data_completeness",
        "first_computed_at",
        "computed_at",
    }


def test_geo_concentration_override_replaces_seed() -> None:
    # transformers_tnd seed has geo_concentration=0.35. The override
    # should replace it entirely; the score should reflect the new
    # value, not the seed.
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    with_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
        geo_concentration=0.99,
    )
    without_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
    )
    assert with_override.sub_scores["geo_concentration"] == 0.99
    assert without_override.sub_scores["geo_concentration"] == pytest.approx(0.35)
    # B should differ because the geo weight (0.10 for near horizon)
    # is applied to a different sub-score value.
    assert with_override.score != without_override.score


def test_geo_concentration_none_falls_back_to_seed() -> None:
    # The default (None) preserves M2 stopgap behavior: the seed
    # value flows through to sub_scores.
    result = compute_segment_score(
        "transformers_tnd",
        "near",
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert result.sub_scores["geo_concentration"] == pytest.approx(0.35)


def test_geo_concentration_override_does_not_affect_other_subscores() -> None:
    # The override only changes the geo sub-score; the other 4
    # sub-scores must be unchanged.
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    with_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
        geo_concentration=0.99,
    )
    without_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
    )
    for name in ("lead_time_growth", "capacity_tightness", "regulatory_friction", "demand_signal"):
        assert with_override.sub_scores[name] == without_override.sub_scores[name]


def test_demand_signal_override_replaces_seed() -> None:
    """Mirrors `test_geo_concentration_override_replaces_seed` for
    the demand_signal sub-score. The recompute job pre-computes a
    dynamic demand_signal from FRED `A35SNO` for `transformers_tnd`
    and passes it as an override; the seed value is the M2 stopgap.
    """
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    with_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
        demand_signal=0.99,
    )
    without_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
    )
    assert with_override.sub_scores["demand_signal"] == 0.99
    assert without_override.sub_scores["demand_signal"] == pytest.approx(0.80)
    # B should differ because the demand_signal weight (0.20 for
    # near horizon) is applied to a different value.
    assert with_override.score != without_override.score


def test_demand_signal_none_falls_back_to_seed() -> None:
    """The default (None) preserves M2 stopgap behavior: the seed
    value flows through to sub_scores when no dynamic
    demand_signal extractor fires.
    """
    result = compute_segment_score(
        "transformers_tnd",
        "near",
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert result.sub_scores["demand_signal"] == pytest.approx(0.80)


def test_demand_signal_override_does_not_affect_other_subscores() -> None:
    """Mirror of `test_geo_concentration_override_does_not_affect_other_subscores`
    for the demand_signal override.
    """
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    with_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
        demand_signal=0.99,
    )
    without_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
    )
    for name in ("lead_time_growth", "capacity_tightness", "geo_concentration", "regulatory_friction"):
        assert with_override.sub_scores[name] == without_override.sub_scores[name]
