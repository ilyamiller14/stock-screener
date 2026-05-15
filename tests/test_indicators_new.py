"""
Tests for new v2 indicators added to screener.indicators.
The OHLCV-dependent functions are tested via small synthetic DataFrames.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _make_df(closes, opens=None, highs=None, lows=None, volumes=None):
    """Build a minimal OHLCV DataFrame from a list of closes."""
    n = len(closes)
    closes = np.asarray(closes, dtype=float)
    opens   = np.asarray(opens   if opens   is not None else closes, dtype=float)
    highs   = np.asarray(highs   if highs   is not None else closes * 1.005, dtype=float)
    lows    = np.asarray(lows    if lows    is not None else closes * 0.995, dtype=float)
    volumes = np.asarray(volumes if volumes is not None else np.ones(n) * 1_000_000, dtype=float)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=idx,
    )


# ── ema200_rising_sessions ────────────────────────────────────────────────────

class TestEma200RisingSessions:
    def test_rising_for_full_window(self):
        from screener.indicators import compute_ema200_rising_sessions
        df = _make_df(np.linspace(10, 50, 250))
        result = compute_ema200_rising_sessions(df)
        assert result["ema200_rising_sessions"] >= 22

    def test_flat_returns_zero(self):
        from screener.indicators import compute_ema200_rising_sessions
        df = _make_df([20.0] * 250)
        result = compute_ema200_rising_sessions(df)
        assert result["ema200_rising_sessions"] == 0

    def test_recently_turned_up_returns_small_count(self):
        from screener.indicators import compute_ema200_rising_sessions
        closes = np.concatenate([np.full(240, 20.0), np.linspace(20, 25, 10)])
        df = _make_df(closes)
        result = compute_ema200_rising_sessions(df)
        assert 0 < result["ema200_rising_sessions"] < 22


# ── Climactic / reversal / volatility metrics ─────────────────────────────────

class TestRecentMoveMetrics:
    def test_max_1d_move_120d(self):
        from screener.indicators import compute_recent_move_metrics
        closes = [100.0] * 100 + [120.0] + [120.0] * 19
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        assert result["max_1d_move_120d"] == pytest.approx(20.0, abs=0.01)

    def test_max_1d_move_120d_outside_window(self):
        from screener.indicators import compute_recent_move_metrics
        closes = [100.0] * 50 + [120.0] + [120.0] * 150
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        assert result["max_1d_move_120d"] < 1.0

    def test_max_gap_120d(self):
        from screener.indicators import compute_recent_move_metrics
        n = 200
        closes = [100.0] * n
        opens = [100.0] * n
        opens[150] = 125.0
        df = _make_df(closes, opens=opens)
        result = compute_recent_move_metrics(df)
        assert result["max_gap_120d"] == pytest.approx(25.0, abs=0.01)

    def test_concentration_60d(self):
        from screener.indicators import compute_recent_move_metrics
        closes = [100.0] * 140 + list(np.linspace(100, 110, 30)) + [121.0] + list(np.linspace(121, 120, 29))
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        assert 30.0 < result["concentration_60d"] < 70.0

    def test_concentration_zero_when_no_rally(self):
        from screener.indicators import compute_recent_move_metrics
        df = _make_df([50.0] * 200)
        result = compute_recent_move_metrics(df)
        assert result["concentration_60d"] == 0.0

    def test_dist_from_recent_highs(self):
        from screener.indicators import compute_recent_move_metrics
        closes = [100.0] * 195 + [100.0, 102.0, 105.0, 103.0, 101.0]
        highs = closes.copy()
        df = _make_df(closes, highs=highs)
        result = compute_recent_move_metrics(df)
        assert result["dist_from_5d_high_pct"] == pytest.approx(3.81, abs=0.05)

    def test_vol_60d(self):
        from screener.indicators import compute_recent_move_metrics
        df = _make_df([100.0] * 200)
        result = compute_recent_move_metrics(df)
        assert result["vol_60d"] == pytest.approx(0.0, abs=0.001)

    def test_vol_60d_volatile_series(self):
        from screener.indicators import compute_recent_move_metrics
        rng = np.random.default_rng(seed=42)
        rets = rng.choice([-0.05, 0.05], size=200)
        closes = 100 * np.cumprod(1 + rets)
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        assert 4.0 < result["vol_60d"] < 6.0


class TestTrendCleanliness:
    def test_r2_perfect_uptrend(self):
        from screener.indicators import compute_trend_cleanliness
        closes = 100 * np.exp(np.linspace(0, 0.6, 200))
        df = _make_df(closes)
        result = compute_trend_cleanliness(df)
        assert result["r2_log_60d"] > 0.95

    def test_r2_flat_series(self):
        from screener.indicators import compute_trend_cleanliness
        rng = np.random.default_rng(seed=7)
        closes = 100 + rng.normal(0, 0.001, 200)
        df = _make_df(closes)
        result = compute_trend_cleanliness(df)
        assert result["r2_log_60d"] < 0.5

    def test_outlier_bar_count_clean(self):
        from screener.indicators import compute_trend_cleanliness
        closes = 100 * np.exp(np.linspace(0, 0.3, 200))
        df = _make_df(closes)
        result = compute_trend_cleanliness(df)
        assert result["outlier_bar_count_60d"] == 0

    def test_outlier_bar_count_with_spike(self):
        from screener.indicators import compute_trend_cleanliness
        closes = [100.0] * 199 + [115.0]
        df = _make_df(closes)
        result = compute_trend_cleanliness(df)
        assert result["outlier_bar_count_60d"] >= 1


# ── ADX (including robust variant) ────────────────────────────────────────────

class TestRobustADX:
    def test_robust_adx_lower_than_naive_on_spiky_series(self):
        pytest.importorskip("pandas_ta")
        from screener.indicators import compute_adx
        n = 100
        closes = [100.0] * n
        highs = [100.5] * n
        lows = [99.5] * n
        highs[80] = 150.0
        df = _make_df(closes, highs=highs, lows=lows)
        result = compute_adx(df)
        assert "adx_robust" in result
        assert result["adx_robust"] <= result["adx_14"]

    def test_robust_adx_matches_naive_on_smooth_series(self):
        pytest.importorskip("pandas_ta")
        from screener.indicators import compute_adx
        closes = list(np.linspace(100, 130, 200))
        df = _make_df(closes)
        result = compute_adx(df)
        assert abs(result["adx_robust"] - result["adx_14"]) < 5.0


class TestPivotProximity:
    def test_finds_recent_consolidation(self):
        from screener.indicators import compute_pivot_proximity
        rise = list(np.linspace(80, 100, 30))
        base = [98.0, 96.0, 99.0, 95.0, 100.0, 97.0, 96.0, 99.0, 98.0, 100.0,
                97.0, 95.0, 99.0, 98.0, 96.0, 100.0, 99.0, 97.0, 96.0, 100.0]
        closes = rise + base
        df = _make_df(closes, highs=closes)
        result = compute_pivot_proximity(df)
        assert result["pivot_price"] == pytest.approx(100.0, abs=2.0)
        assert abs(result["dist_from_pivot_pct"]) < 5.0
        assert 15 <= result["base_length_days"] <= 40

    def test_no_valid_base_returns_zero(self):
        from screener.indicators import compute_pivot_proximity
        closes = list(np.linspace(50, 100, 200))
        df = _make_df(closes, highs=closes)
        result = compute_pivot_proximity(df)
        assert result["pivot_price"] == 0.0
        assert result["dist_from_pivot_pct"] == 99.0

    def test_extended_past_pivot(self):
        from screener.indicators import compute_pivot_proximity
        base = [95.0, 100.0, 96.0, 99.0, 100.0, 95.0, 98.0, 100.0, 97.0, 99.0,
                95.0, 100.0, 96.0, 99.0, 100.0, 95.0, 98.0, 100.0, 97.0, 99.0]
        breakout = list(np.linspace(101, 115, 10))
        closes = [80.0] * 30 + base + breakout
        df = _make_df(closes, highs=closes)
        result = compute_pivot_proximity(df)
        assert result["pivot_price"] == pytest.approx(100.0, abs=2.0)
        assert result["dist_from_pivot_pct"] > 10.0
