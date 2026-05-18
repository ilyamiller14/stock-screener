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


class TestRSLine:
    def test_rs_line_at_new_high(self):
        from screener.indicators import compute_rs_line
        n = 200
        ticker_closes = 100 * np.exp(np.linspace(0, 0.5, n))
        bench_closes  = 100 * np.exp(np.linspace(0, 0.1, n))
        tdf = _make_df(ticker_closes)
        bdf = _make_df(bench_closes)
        result = compute_rs_line(tdf, bdf)
        assert result["rs_line_at_50d_high"] is True

    def test_rs_line_below_recent_high(self):
        from screener.indicators import compute_rs_line
        n = 200
        ticker_closes = np.concatenate([
            100 * np.exp(np.linspace(0, 0.5, 150)),
            165 + np.linspace(0, -10, 50),
        ])
        bench_closes = 100 * np.exp(np.linspace(0, 0.3, 200))
        tdf = _make_df(ticker_closes)
        bdf = _make_df(bench_closes)
        result = compute_rs_line(tdf, bdf)
        assert result["rs_line_at_50d_high"] is False


class TestPullbackVolume:
    def test_dryup_when_pullback_has_low_volume(self):
        from screener.indicators import compute_pullback_volume_ratio
        n = 30
        closes = np.concatenate([np.full(20, 100.0), [100, 99, 98, 97, 98, 100, 101, 102, 103, 105]])
        volumes = np.ones(n) * 1_000_000
        volumes[21:24] = 300_000
        df = _make_df(closes, volumes=volumes)
        result = compute_pullback_volume_ratio(df)
        assert result["pullback_vol_ratio"] < 0.6

    def test_no_pullback_returns_neutral(self):
        from screener.indicators import compute_pullback_volume_ratio
        closes = list(np.linspace(100, 130, 30))
        df = _make_df(closes)
        result = compute_pullback_volume_ratio(df)
        assert result["pullback_vol_ratio"] == 1.0


# ── v2.1 additions ───────────────────────────────────────────────────────────

class TestMaxRange120d:
    def test_max_range_120d_detects_wide_intraday_bar(self):
        """CPRX-style: bar with huge intraday range but only modest close-to-close move."""
        from screener.indicators import compute_recent_move_metrics
        n = 200
        closes = [100.0] * n + [107.0]
        highs  = [100.5] * n + [120.0]
        lows   = [99.5]  * n + [98.0]
        opens  = [100.0] * n + [100.0]
        df = _make_df(closes, opens=opens, highs=highs, lows=lows)
        result = compute_recent_move_metrics(df)
        # Range pct = (120 - 98) / 100 (prev close) = 22%
        assert result["max_range_120d"] == pytest.approx(22.0, abs=0.5)

    def test_max_range_120d_quiet_series(self):
        from screener.indicators import compute_recent_move_metrics
        closes = [100.0] * 200
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        assert result["max_range_120d"] < 2.0


class TestConcentrationWindows:
    def test_concentration_20d_window(self):
        """Concentration over a 20-day window catches recent climactic clusters."""
        from screener.indicators import compute_recent_move_metrics
        # 180 quiet bars, then 12 flat + 1 +8% bar + 7 flat
        closes = [100.0] * 180 + [100.0] * 12 + [108.0] + [108.0] * 7
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        # 20d return ~8%, biggest 1d ~8% → ~100% concentration
        assert result["concentration_20d"] > 80.0

    def test_concentration_120d_window(self):
        """Concentration over 120d catches CWAN-style mid-window spikes."""
        from screener.indicators import compute_recent_move_metrics
        # Quiet 80 + flat 20 + spike + flat 99 → 120-day window contains the spike
        closes = [100.0] * 80 + [100.0] * 20 + [108.0] + [108.0] * 99
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        assert result["concentration_120d"] > 80.0

    def test_concentration_zero_when_total_return_under_5pct(self):
        """ATEN-style false positive guard: one big bar then sideways → low total return.
        Concentration should NOT compute on small denominators — that's healthy
        consolidation, not climactic action."""
        from screener.indicators import compute_recent_move_metrics
        # Stock with one +10% bar in last 20 sessions but otherwise sideways
        # 20d total return = ~4% (under 5% guard) → concentration_20d should be 0
        closes = [100.0] * 180 + [100.0] * 5 + [110.0] + [104.0] * 14
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        assert result["concentration_20d"] == 0.0


class TestRallyFreshness:
    """rally_freshness_pct = recent_60d_return / total_252d_return * 100

    Detects post-news drift patterns where most of the 1-year gain happened
    long ago (CSGS: spike 136d ago, last 60d basically flat → freshness ~4%)
    vs. healthy ongoing climbs (HPE: 60d return is a meaningful slice of 1y).
    """

    def test_fresh_rally_high_score(self):
        """Steady linear climber: 60d return is a large fraction of 1y return."""
        from screener.indicators import compute_recent_move_metrics
        # Linear ramp from 100 to 150 over 252 sessions
        closes = list(np.linspace(100.0, 150.0, 252))
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        # Last 60d gain ~12 points / 252d gain 50 points = ~24%
        assert result["rally_freshness_pct"] >= 15.0

    def test_stale_rally_low_score(self):
        """CSGS-style post-news drift: 1y rally was an old spike, recent 60d flat."""
        from screener.indicators import compute_recent_move_metrics
        # 90 quiet bars at 60, +15 bar to 70, 160 quiet bars near 70 → 1y return ~17%, 60d return ~0
        closes = [60.0] * 90 + [70.0] + [70.0] * 160
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        assert result["rally_freshness_pct"] < 10.0

    def test_freshness_returns_default_when_no_1y_rally(self):
        """If 1y return is small or negative, freshness is meaningless → return default 100."""
        from screener.indicators import compute_recent_move_metrics
        closes = [100.0] * 252
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        # No meaningful denominator → default 100 (= "fresh enough, don't penalize")
        assert result["rally_freshness_pct"] == 100.0
