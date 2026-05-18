"""Unit tests for Tier 3 penalty multipliers (v2.1 tuning)."""
from __future__ import annotations

from screener import penalties


def _ind(**overrides):
    base = {
        "max_1d_move_120d": 5.0,
        "max_gap_120d": 3.0,
        "max_range_120d": 5.0,
        "concentration_20d": 20.0,
        "concentration_60d": 20.0,
        "concentration_120d": 20.0,
        "dist_from_5d_high_pct": 1.0,
        "pct_above_52w_low": 50.0,
        "extension_atr_multiple": 1.0,
        "extension_ema50_pct": 5.0,
    }
    base.update(overrides)
    return base


# ── Climactic single-bar (now 8/12/20 from v2.0's 10/15/20) ───────────────────

class TestClimacticPenalties:
    def test_clean_stock_no_penalty(self):
        out = penalties.compute_penalty_multiplier(_ind())
        assert out["final_multiplier"] == 1.0
        assert out["triggered"] == []

    def test_mild_threshold_at_8pct(self):
        """v2.1: mild threshold 10→8."""
        out = penalties.compute_penalty_multiplier(_ind(max_1d_move_120d=8.5))
        assert "climactic_mild" in out["triggered"]

    def test_just_under_8pct_no_penalty(self):
        """7.9% should not trigger anything."""
        out = penalties.compute_penalty_multiplier(_ind(max_1d_move_120d=7.9))
        assert "climactic_mild" not in out["triggered"]

    def test_severe_at_20pct(self):
        out = penalties.compute_penalty_multiplier(_ind(max_1d_move_120d=22.0))
        assert out["final_multiplier"] <= 0.30
        assert "climactic_severe" in out["triggered"]


# ── Exhaustion gap (unchanged at 10/15) ───────────────────────────────────────

class TestGapPenalties:
    def test_mild_gap(self):
        out = penalties.compute_penalty_multiplier(_ind(max_gap_120d=12.0))
        assert 0.70 <= out["final_multiplier"] < 1.0
        assert "exhaustion_gap_mild" in out["triggered"]


# ── Wide-Spread Wide-Range bar (NEW in v2.1) ──────────────────────────────────

class TestWSWRPenalties:
    def test_wide_range_mild_at_15pct(self):
        """Intraday range ≥15% triggers mild WSWR penalty."""
        out = penalties.compute_penalty_multiplier(_ind(max_range_120d=16.0))
        assert "wswr_mild" in out["triggered"]
        assert out["final_multiplier"] < 1.0

    def test_wide_range_heavy_at_22pct(self):
        """Intraday range ≥22% triggers heavy WSWR penalty (CPRX April 27 was 19.2%)."""
        out = penalties.compute_penalty_multiplier(_ind(max_range_120d=23.0))
        assert "wswr_heavy" in out["triggered"]
        assert out["final_multiplier"] <= 0.50

    def test_quiet_range_no_penalty(self):
        out = penalties.compute_penalty_multiplier(_ind(max_range_120d=8.0))
        assert all(not t.startswith("wswr") for t in out["triggered"])


# ── Rally concentration (max of 20/60/120-day windows) ────────────────────────

class TestConcentrationMultiWindow:
    def test_60d_concentration_still_fires(self):
        out = penalties.compute_penalty_multiplier(_ind(concentration_60d=70.0))
        assert "concentration_severe" in out["triggered"]

    def test_20d_concentration_fires_when_60d_quiet(self):
        """CPRX-style: spike clustered in last 20d, diluted in 60d window."""
        out = penalties.compute_penalty_multiplier(_ind(
            concentration_20d=78.0,
            concentration_60d=25.0,
            concentration_120d=19.0,
        ))
        assert any(t.startswith("concentration") for t in out["triggered"])

    def test_120d_concentration_fires_when_60d_quiet(self):
        """CWAN-style: spike 99d ago, diluted in 60d window."""
        out = penalties.compute_penalty_multiplier(_ind(
            concentration_20d=15.0,
            concentration_60d=25.0,
            concentration_120d=47.0,
        ))
        assert any(t.startswith("concentration") for t in out["triggered"])

    def test_all_windows_clean_no_penalty(self):
        out = penalties.compute_penalty_multiplier(_ind(
            concentration_20d=15.0,
            concentration_60d=20.0,
            concentration_120d=22.0,
        ))
        assert not any(t.startswith("concentration") for t in out["triggered"])


# ── Reversal (now 5/10 from v2.0's 3/7) ───────────────────────────────────────

class TestReversalPenalties:
    def test_no_penalty_under_5pct(self):
        """v2.1: mild threshold 3→5. A 3% pullback is normal noise."""
        out = penalties.compute_penalty_multiplier(_ind(dist_from_5d_high_pct=4.0))
        assert "reversal_mild" not in out["triggered"]

    def test_mild_at_5pct(self):
        out = penalties.compute_penalty_multiplier(_ind(dist_from_5d_high_pct=6.0))
        assert "reversal_mild" in out["triggered"]

    def test_heavy_at_10pct(self):
        """v2.1: heavy threshold 7→10."""
        out = penalties.compute_penalty_multiplier(_ind(dist_from_5d_high_pct=11.0))
        assert "reversal_heavy" in out["triggered"]


# ── 52w-low extension (now 100/200/400 from v2.0's 60/120/250) ────────────────

class TestExtensionPenalties:
    def test_no_penalty_at_80pct_above_52w_low(self):
        """v2.1: stocks 60-100% above 52w low are healthy leaders, not over-extended."""
        out = penalties.compute_penalty_multiplier(_ind(pct_above_52w_low=80.0))
        assert not any(t.startswith("52w_low") for t in out["triggered"])

    def test_mild_at_120pct(self):
        out = penalties.compute_penalty_multiplier(_ind(pct_above_52w_low=130.0))
        assert "52w_low_mild" in out["triggered"]

    def test_heavy_at_200pct(self):
        out = penalties.compute_penalty_multiplier(_ind(pct_above_52w_low=220.0))
        assert "52w_low_heavy" in out["triggered"]

    def test_severe_at_400pct(self):
        out = penalties.compute_penalty_multiplier(_ind(pct_above_52w_low=420.0))
        assert "52w_low_severe" in out["triggered"]


# ── Composition / floor ───────────────────────────────────────────────────────

class TestComposition:
    def test_multiple_triggers_take_minimum(self):
        out = penalties.compute_penalty_multiplier(_ind(
            max_1d_move_120d=22.0,
            dist_from_5d_high_pct=11.0,
        ))
        # severe climactic (0.25) is the floor
        assert out["final_multiplier"] <= 0.30

    def test_floor_at_005(self):
        out = penalties.compute_penalty_multiplier(_ind(
            max_1d_move_120d=22.0,
            max_gap_120d=18.0,
            concentration_60d=80.0,
            dist_from_5d_high_pct=15.0,
            pct_above_52w_low=500.0,
            max_range_120d=30.0,
        ))
        assert out["final_multiplier"] >= 0.05
