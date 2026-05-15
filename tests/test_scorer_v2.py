"""End-to-end v2 scorer tests: real indicator dicts → composite score."""
from __future__ import annotations

from screener import scorer


def _clean_trend_ind(**overrides):
    """A canonical clean Stage-2 stock (GLNG-like)."""
    base = {
        "ticker": "GLNG_LIKE",
        "close": 57.0, "avg_volume_20d": 1_500_000,
        "ema21": 55.0, "ema50": 52.0, "ema150": 48.0, "ema200": 45.0,
        "ema_aligned": True,
        "ema200_slope": 0.35, "ema200_slope_positive": True,
        "ema200_rising_sessions": 60,
        "adx_14": 30.0, "adx_robust": 28.0,
        "dist_from_52w_high_pct": 1.0, "pct_above_52w_low": 55.0,
        "obv_slope_norm": 4.0, "cmf_20": 0.12,
        "volume_ratio": 1.2, "upvol_ratio": 0.65, "pullback_vol_ratio": 0.7,
        "rs_3m_percentile": 80, "rs_6m_percentile": 78,
        "rs_12m_percentile": 75, "ibd_rs_percentile": 82,
        "rs_line_at_50d_high": True,
        "vcp_score": 55.0, "squeeze_score": 40.0,
        "pivot_price": 56.5, "dist_from_pivot_pct": 0.9, "base_depth_pct": 6.0, "base_length_days": 22,
        "r2_log_60d": 0.78, "outlier_bar_count_60d": 0,
        "max_1d_move_120d": 6.0, "max_gap_120d": 4.0,
        "concentration_60d": 22.0, "dist_from_5d_high_pct": 1.0,
        "extension_atr_multiple": 1.5, "extension_ema50_pct": 9.0,
    }
    base.update(overrides)
    return base


def _slab_like_ind(**overrides):
    """SLAB-style post-spike drift — should be rejected by gate."""
    base = _clean_trend_ind(
        ticker="SLAB_LIKE",
        adx_14=54.0, adx_robust=18.0,
        r2_log_60d=0.85, outlier_bar_count_60d=1,
        max_1d_move_120d=49.0, max_gap_120d=50.0,
        concentration_60d=19.0,
        vcp_score=70.0,
        rs_3m_percentile=22.0,
    )
    base.update(overrides)
    return base


class TestV2CompositeScore:
    def test_clean_trend_qualifies_and_scores_high(self):
        out = scorer.compute_composite(_clean_trend_ind())
        assert out["qualifies"] is True
        assert out["composite_score"] > 55.0

    def test_slab_like_rejected_by_gate(self):
        out = scorer.compute_composite(_slab_like_ind())
        assert out["qualifies"] is False
        # Reason should reference the climactic 1d move or gap
        assert any(kw in out["fail_reason"] for kw in ("climactic", "1d_move", "exhaustion", "gap"))

    def test_borderline_post_spike_drifts_get_penalized(self):
        out = scorer.compute_composite(_clean_trend_ind(max_1d_move_120d=16.0))
        assert out["qualifies"] is True
        assert out["composite_score"] < 50.0

    def test_reversing_stock_penalized(self):
        out = scorer.compute_composite(_clean_trend_ind(dist_from_5d_high_pct=8.0))
        assert out["qualifies"] is True
        assert "reversal_heavy" in out["penalty_triggered"]


class TestRanking:
    def test_clean_outranks_post_spike(self):
        clean  = scorer.compute_composite(_clean_trend_ind())
        warned = scorer.compute_composite(_clean_trend_ind(max_1d_move_120d=15.0))
        assert clean["composite_score"] > warned["composite_score"]
