"""Unit tests for Tier 2 setup quality scoring."""
from __future__ import annotations

from screener import setup_score


def _baseline_ind(**overrides):
    base = {
        "close": 50.0, "avg_volume_20d": 1_000_000,
        "ema21": 49.0, "ema50": 47.0, "ema150": 44.0, "ema200": 42.0,
        "ema_aligned": True,
        "ema200_slope": 0.20,
        "ema200_rising_sessions": 30,
        "adx_14": 30.0, "adx_robust": 28.0,
        "dist_from_52w_high_pct": 5.0,
        "pct_above_52w_low": 60.0,
        "rsi_14": 60.0,
        "macd_hist": 0.05,
        "macd_crossover_sessions_ago": 5,
        "obv_slope_norm": 3.0,
        "cmf_20": 0.10,
        "upvol_ratio": 0.6,
        "volume_ratio": 1.2,
        "pullback_vol_ratio": 0.7,
        "rs_3m_percentile": 80.0,
        "rs_6m_percentile": 75.0,
        "rs_12m_percentile": 70.0,
        "ibd_rs_percentile": 85.0,
        "rs_line_at_50d_high": True,
        "vcp_score": 60.0,
        "squeeze_score": 50.0,
        "pivot_price": 50.0,
        "dist_from_pivot_pct": 0.5,
        "r2_log_60d": 0.85,
        "outlier_bar_count_60d": 0,
        "max_1d_move_120d": 8.0,
        "max_gap_120d": 5.0,
    }
    base.update(overrides)
    return base


class TestTrendStrength:
    def test_high_score_for_clean_trend(self):
        s = setup_score.score_trend_strength(_baseline_ind())
        assert s > 70.0

    def test_zero_for_unaligned(self):
        s = setup_score.score_trend_strength(_baseline_ind(ema_aligned=False))
        assert s < 80.0

    def test_robust_adx_used(self):
        s_robust = setup_score.score_trend_strength(_baseline_ind(adx_14=54.0, adx_robust=15.0))
        s_naive  = setup_score.score_trend_strength(_baseline_ind(adx_14=54.0, adx_robust=54.0))
        assert s_robust < s_naive


class TestTrendCleanliness:
    def test_high_r2_full_credit(self):
        s = setup_score.score_trend_cleanliness(_baseline_ind(r2_log_60d=0.95, outlier_bar_count_60d=0))
        assert s > 90.0

    def test_low_r2_zero(self):
        s = setup_score.score_trend_cleanliness(_baseline_ind(r2_log_60d=0.05, outlier_bar_count_60d=0))
        assert s < 50.0

    def test_outlier_bars_zero_credit(self):
        s = setup_score.score_trend_cleanliness(_baseline_ind(r2_log_60d=0.95, outlier_bar_count_60d=5))
        assert s < 70.0


class TestRelativeStrength:
    def test_high_rs_with_bonus(self):
        s = setup_score.score_rs(_baseline_ind(
            ibd_rs_percentile=95.0, rs_3m_percentile=95.0,
            rs_6m_percentile=95.0, rs_12m_percentile=95.0,
            rs_line_at_50d_high=True,
        ))
        assert s == 100.0

    def test_no_bonus_when_rs_line_not_at_high(self):
        s_with    = setup_score.score_rs(_baseline_ind(rs_line_at_50d_high=True, ibd_rs_percentile=80.0))
        s_without = setup_score.score_rs(_baseline_ind(rs_line_at_50d_high=False, ibd_rs_percentile=80.0))
        assert s_with > s_without


class TestBaseSetup:
    def test_vcp_skipped_after_spike(self):
        s_guarded = setup_score.score_base_setup(_baseline_ind(vcp_score=80.0, max_1d_move_120d=15.0))
        s_clean   = setup_score.score_base_setup(_baseline_ind(vcp_score=80.0, max_1d_move_120d=5.0))
        assert s_guarded < s_clean

    def test_pivot_proximity_at_pivot(self):
        s = setup_score.score_base_setup(_baseline_ind(dist_from_pivot_pct=0.5, pivot_price=50.0))
        assert s > 50.0

    def test_pivot_proximity_too_extended(self):
        s_extended = setup_score.score_base_setup(_baseline_ind(dist_from_pivot_pct=8.0, pivot_price=50.0))
        s_at       = setup_score.score_base_setup(_baseline_ind(dist_from_pivot_pct=0.5, pivot_price=50.0))
        assert s_extended < s_at


class TestVolumeProfile:
    def test_dryup_on_pullback_scores_high(self):
        s_dry   = setup_score.score_volume_profile(_baseline_ind(pullback_vol_ratio=0.5))
        s_surge = setup_score.score_volume_profile(_baseline_ind(pullback_vol_ratio=1.5))
        assert s_dry > s_surge

    def test_breakout_volume_only_at_pivot(self):
        s_far = setup_score.score_volume_profile(_baseline_ind(dist_from_pivot_pct=8.0, volume_ratio=2.0))
        s_at  = setup_score.score_volume_profile(_baseline_ind(dist_from_pivot_pct=0.5, volume_ratio=2.0))
        assert s_at > s_far


class TestComposite:
    def test_compute_setup_score_returns_dict(self):
        out = setup_score.compute_setup_score(_baseline_ind())
        for k in ("trend_strength", "trend_cleanliness", "rs", "base_setup", "volume_profile", "raw_setup_score"):
            assert k in out
        assert 0 <= out["raw_setup_score"] <= 100
