"""Unit tests for Tier 1 qualification gate."""
from __future__ import annotations

from screener import qualify


def _passing_ind(**overrides):
    """Indicator dict that passes the full Tier 1 gate."""
    base = {
        "ticker": "TEST",
        "close": 50.0,
        "avg_volume_20d": 1_000_000,
        "ema21": 49.0, "ema50": 47.0, "ema150": 44.0, "ema200": 42.0,
        "ema_aligned": True,
        "ema200_slope": 0.20,
        "ema200_slope_positive": True,
        "ema200_rising_sessions": 30,
        "adx_14": 25.0,
        "dist_from_52w_high_pct": 8.0,
        "pct_above_52w_low": 50.0,
        "max_1d_move_120d": 8.0,
        "max_gap_120d": 5.0,
        "vol_60d": 2.5,
    }
    base.update(overrides)
    return base


class TestQualifyHappyPath:
    def test_passing_indicators_qualify(self):
        ok, reason = qualify.qualifies(_passing_ind())
        assert ok is True
        assert reason == ""


class TestQualifyMinervini:
    def test_fails_below_ema200(self):
        ok, reason = qualify.qualifies(_passing_ind(ema_aligned=False, ema200=51.0))
        assert ok is False
        assert "ema_aligned" in reason or "ema200" in reason

    def test_fails_ema50_below_ema150(self):
        ok, reason = qualify.qualifies(_passing_ind(ema50=43.0))
        assert ok is False

    def test_fails_ema150_below_ema200(self):
        ok, reason = qualify.qualifies(_passing_ind(ema150=41.0))
        assert ok is False

    def test_fails_ema200_not_rising_long_enough(self):
        ok, reason = qualify.qualifies(_passing_ind(ema200_rising_sessions=15))
        assert ok is False
        assert "rising" in reason

    def test_fails_below_30pct_above_52w_low(self):
        ok, reason = qualify.qualifies(_passing_ind(pct_above_52w_low=25.0))
        assert ok is False

    def test_fails_too_far_below_52w_high(self):
        ok, reason = qualify.qualifies(_passing_ind(dist_from_52w_high_pct=30.0))
        assert ok is False


class TestQualityBars:
    def test_fails_below_min_price(self):
        ok, _ = qualify.qualifies(_passing_ind(close=5.0))
        assert ok is False

    def test_fails_below_min_avg_volume(self):
        ok, _ = qualify.qualifies(_passing_ind(avg_volume_20d=100_000))
        assert ok is False


class TestClimacticRejects:
    def test_fails_climactic_1d_move(self):
        ok, reason = qualify.qualifies(_passing_ind(max_1d_move_120d=30.0))
        assert ok is False
        assert "climactic" in reason or "1d_move" in reason

    def test_fails_exhaustion_gap(self):
        ok, reason = qualify.qualifies(_passing_ind(max_gap_120d=22.0))
        assert ok is False

    def test_fails_high_vol_60d(self):
        ok, reason = qualify.qualifies(_passing_ind(vol_60d=10.0))
        assert ok is False
