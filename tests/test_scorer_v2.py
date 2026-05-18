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
        # v2.1: heavy threshold is now 10% (was 7%). Use 11 to trigger heavy.
        out = scorer.compute_composite(_clean_trend_ind(dist_from_5d_high_pct=11.0))
        assert out["qualifies"] is True
        assert "reversal_heavy" in out["penalty_triggered"]


class TestRanking:
    def test_clean_outranks_post_spike(self):
        clean  = scorer.compute_composite(_clean_trend_ind())
        warned = scorer.compute_composite(_clean_trend_ind(max_1d_move_120d=15.0))
        assert clean["composite_score"] > warned["composite_score"]


# ── v2.1 regression tests for 2026-05-18 audit findings ──────────────────────

class TestV21CWANRegression:
    """CWAN slipped through v2.0: 8.4% gap + post-news drift read as a clean VCP base.
    These signatures should now be caught."""

    def test_cwan_like_concentration_120d_fires(self):
        """120d concentration 47% (CWAN actual) must trigger penalty."""
        out = scorer.compute_composite(_clean_trend_ind(
            concentration_20d=15.0,
            concentration_60d=25.0,
            concentration_120d=47.0,
        ))
        assert "concentration_mild" in out["penalty_triggered"]


class TestV21CPRXRegression:
    """CPRX slipped through v2.0: cluster of 6.6-6.9% bars + 19.2% intraday range."""

    def test_cprx_like_climactic_at_new_8pct_threshold(self):
        out = scorer.compute_composite(_clean_trend_ind(max_1d_move_120d=8.5))
        assert "climactic_mild" in out["penalty_triggered"]

    def test_cprx_like_wide_range_bar_fires_wswr(self):
        """A 19.2% intraday-range bar (CPRX April 27) triggers wswr_mild."""
        out = scorer.compute_composite(_clean_trend_ind(max_range_120d=19.2))
        assert "wswr_mild" in out["penalty_triggered"]

    def test_cprx_like_20d_concentration_fires(self):
        """37% concentration_20d (CPRX actual) catches recent climactic cluster."""
        out = scorer.compute_composite(_clean_trend_ind(
            concentration_20d=37.0,
            concentration_60d=25.0,
            concentration_120d=19.0,
        ))
        assert "concentration_mild" in out["penalty_triggered"]


class TestV21ENSRegression:
    """ENS in v2.0: clean Stage-2 grind (raw 68.4) cut to 41 because pct_above_52w_low ~130%
    tripped the OLD 120% heavy threshold. v2.1 raises to 200% — 130% is now only mild."""

    def test_ens_like_not_heavy_penalized(self):
        out = scorer.compute_composite(_clean_trend_ind(pct_above_52w_low=130.0))
        assert "52w_low_heavy" not in out["penalty_triggered"]
        assert out["penalty_multiplier"] >= 0.80


class TestV21BTSGRegression:
    """BTSG: 91% above 52w low should not penalize at all under v2.1 (mild raised 60→100)."""

    def test_btsg_like_no_penalty_at_91pct_above_low(self):
        out = scorer.compute_composite(_clean_trend_ind(pct_above_52w_low=91.0))
        assert not any(t.startswith("52w_low") for t in out["penalty_triggered"])


class TestV22CSGSRegression:
    """CSGS slipped through v2.1: +14.4% gap on Oct 29 (136 days ago) was outside
    the 120d max_gap window. Last 30d stdev 0.10%, sitting at 52w high.
    1y return ~33%, last 60d return ~1.3% → freshness ~4%."""

    def test_csgs_like_stale_rally_fires(self):
        """Freshness ~4% should trigger heavy penalty."""
        out = scorer.compute_composite(_clean_trend_ind(rally_freshness_pct=4.0))
        assert "stale_rally_heavy" in out["penalty_triggered"]
        assert out["penalty_multiplier"] <= 0.50

    def test_healthy_climber_freshness_not_penalized(self):
        """HPE-style: 60d return is ~25% of 1y return → freshness ≥15, no penalty."""
        out = scorer.compute_composite(_clean_trend_ind(rally_freshness_pct=25.0))
        assert not any(t.startswith("stale_rally") for t in out["penalty_triggered"])
