"""Unit tests for Tier 3 penalty multipliers."""
from __future__ import annotations

from screener import penalties


def _ind(**overrides):
    base = {
        "max_1d_move_120d": 5.0,
        "max_gap_120d": 3.0,
        "concentration_60d": 20.0,
        "dist_from_5d_high_pct": 1.0,
        "pct_above_52w_low": 50.0,
        "extension_atr_multiple": 1.0,
        "extension_ema50_pct": 5.0,
    }
    base.update(overrides)
    return base


class TestSpikePenalties:
    def test_clean_stock_no_penalty(self):
        out = penalties.compute_penalty_multiplier(_ind())
        assert out["final_multiplier"] == 1.0
        assert out["triggered"] == []

    def test_mild_spike(self):
        out = penalties.compute_penalty_multiplier(_ind(max_1d_move_120d=11.0))
        assert 0.80 <= out["final_multiplier"] < 1.0
        assert "climactic_mild" in out["triggered"]

    def test_severe_spike(self):
        out = penalties.compute_penalty_multiplier(_ind(max_1d_move_120d=22.0))
        assert out["final_multiplier"] <= 0.30
        assert "climactic_severe" in out["triggered"]


class TestGapPenalties:
    def test_mild_gap(self):
        out = penalties.compute_penalty_multiplier(_ind(max_gap_120d=12.0))
        assert 0.70 <= out["final_multiplier"] < 1.0
        assert "exhaustion_gap_mild" in out["triggered"]


class TestConcentrationPenalties:
    def test_concentrated_rally(self):
        out = penalties.compute_penalty_multiplier(_ind(concentration_60d=70.0))
        assert out["final_multiplier"] <= 0.40
        assert "concentration_severe" in out["triggered"]


class TestReversalPenalties:
    def test_rolling_over(self):
        out = penalties.compute_penalty_multiplier(_ind(dist_from_5d_high_pct=8.0))
        assert out["final_multiplier"] <= 0.50
        assert "reversal_heavy" in out["triggered"]


class TestExtensionPenalties:
    def test_far_above_52w_low(self):
        out = penalties.compute_penalty_multiplier(_ind(pct_above_52w_low=130.0))
        assert out["final_multiplier"] < 1.0
        assert any(t.startswith("52w_low") for t in out["triggered"])


class TestComposition:
    def test_multiple_triggers_take_minimum(self):
        out = penalties.compute_penalty_multiplier(_ind(
            max_1d_move_120d=22.0,
            dist_from_5d_high_pct=8.0,
        ))
        assert out["final_multiplier"] <= 0.25 + 0.01

    def test_floor_at_005(self):
        out = penalties.compute_penalty_multiplier(_ind(
            max_1d_move_120d=22.0,
            max_gap_120d=18.0,
            concentration_60d=80.0,
            dist_from_5d_high_pct=15.0,
            pct_above_52w_low=300.0,
        ))
        assert out["final_multiplier"] >= 0.05
