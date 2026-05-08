"""
Tests for screener.scorer — covers the post-audit scoring fixes:
- Hard filter additions (ADX, dollar-volume, distance from 52w high)
- CMF must penalize negative money flow
- MACD histogram score graduated (not saturated)
- EMA200 slope graduated (not saturated)
- volume_ratio used as a real scoring component
- Stage 2 sub-score graduated, not binary
"""
from __future__ import annotations

from screener import config, scorer


# ── Helper: build a "passing" indicator dict ──────────────────────────────────

def make_ind(**overrides):
    """A minimal qualifying indicator dict with all defaults set to pass filter."""
    base = {
        "ticker": "TEST",
        "close": 50.0,
        "avg_volume_20d": 2_000_000,        # 2M shares avg
        "ema21": 49.0, "ema50": 47.0, "ema150": 44.0, "ema200": 42.0,
        "ema_aligned": True,
        "ema200_slope": 0.20,                # 0.2% per day
        "ema200_slope_positive": True,
        "rsi_14": 60.0,
        "macd_hist": 0.10,
        "macd_crossover_sessions_ago": 5,
        "adx_14": 30.0,
        "adx_trending": True,
        "obv_trend": "rising",
        "obv_slope_norm": 5.0,
        "cmf_20": 0.20,
        "upvol_ratio": 0.65,
        "volume_ratio": 1.5,
        "rs_3m_percentile": 80.0,
        "rs_6m_percentile": 75.0,
        "ibd_rs_percentile": 78.0,
        "vcp_score": 50.0,
        "squeeze_score": 50.0,
        "near_52w_high": True,
        "dist_from_52w_high_pct": 5.0,
        "pct_above_52w_low": 60.0,
        "extension_atr_multiple": 1.5,
        "extension_ema50_pct": 5.0,
        "max_gap_pct": 2.0,
    }
    base.update(overrides)
    return base


# ── Hard filter ────────────────────────────────────────────────────────────────

class TestHardFilter:
    def test_qualifying_stock_passes(self):
        assert scorer.passes_hard_filters(make_ind()) is True

    def test_low_price_rejected(self):
        assert scorer.passes_hard_filters(make_ind(close=1.5)) is False

    def test_low_share_volume_rejected(self):
        assert scorer.passes_hard_filters(make_ind(avg_volume_20d=50_000)) is False

    def test_below_ema200_rejected(self):
        assert scorer.passes_hard_filters(make_ind(close=40.0, ema200=42.0)) is False

    def test_negative_ema200_slope_rejected(self):
        assert scorer.passes_hard_filters(make_ind(ema200_slope_positive=False)) is False

    # NEW filter behavior:
    def test_low_dollar_volume_rejected(self):
        # close 5.0 * avg_vol 1_000_000 = $5M/day — below threshold
        bad = make_ind(close=5.0, avg_volume_20d=1_000_000,
                       ema21=4.9, ema50=4.7, ema150=4.4, ema200=4.2)
        assert scorer.passes_hard_filters(bad) is False

    def test_high_dollar_volume_passes(self):
        # close 50 * avg_vol 1M = $50M/day — well above threshold
        good = make_ind(close=50.0, avg_volume_20d=1_000_000)
        assert scorer.passes_hard_filters(good) is True

    def test_low_adx_rejected(self):
        # ADX 15 = no real trend — Stage 2 picks should require ADX > 20
        assert scorer.passes_hard_filters(make_ind(adx_14=15.0)) is False

    def test_strong_adx_passes(self):
        assert scorer.passes_hard_filters(make_ind(adx_14=25.0)) is True

    def test_far_from_52w_high_rejected(self):
        # >25% below 52w high is too far for a Stage 2 trend-follower
        assert scorer.passes_hard_filters(make_ind(dist_from_52w_high_pct=30.0)) is False

    def test_near_52w_high_passes(self):
        assert scorer.passes_hard_filters(make_ind(dist_from_52w_high_pct=10.0)) is True


# ── Volume score (CMF, volume_ratio) ──────────────────────────────────────────

class TestVolumeScore:
    def test_strongly_negative_cmf_scores_low(self):
        """CMF -0.5 (heavy distribution) must produce a very low CMF contribution."""
        s_neg = scorer._score_volume(make_ind(cmf_20=-0.5))
        s_pos = scorer._score_volume(make_ind(cmf_20=0.5))
        # The negative-CMF stock should score noticeably lower.
        assert s_pos - s_neg >= 15.0

    def test_zero_cmf_below_neutral(self):
        """A stock with neutral CMF should not get half-credit; 0 ≈ low score."""
        s = scorer._score_volume(make_ind(cmf_20=0.0, obv_slope_norm=0.0,
                                          upvol_ratio=0.0, volume_ratio=1.0))
        # Pure-neutral inputs across the board → not getting 50+ from CMF alone
        assert s < 50.0

    def test_volume_ratio_below_average_lowers_score(self):
        """Today's volume below 20d average should reduce volume score."""
        high_vr = scorer._score_volume(make_ind(volume_ratio=2.0))
        low_vr  = scorer._score_volume(make_ind(volume_ratio=0.5))
        assert high_vr > low_vr + 10.0

    def test_breakout_volume_rewarded(self):
        """A 2x+ volume spike should noticeably increase the volume score."""
        baseline = scorer._score_volume(make_ind(volume_ratio=1.0))
        breakout = scorer._score_volume(make_ind(volume_ratio=2.5))
        assert breakout > baseline + 5.0


# ── Momentum score (MACD hist normalisation) ──────────────────────────────────

class TestMomentumScore:
    def test_macd_hist_does_not_saturate_on_tiny_positive(self):
        """A barely-positive MACD hist must not score the same as a strong one."""
        ind_tiny   = make_ind(macd_hist=0.005, rsi_14=60.0, macd_crossover_sessions_ago=999)
        ind_strong = make_ind(macd_hist=0.500, rsi_14=60.0, macd_crossover_sessions_ago=999)
        s_tiny   = scorer._score_momentum(ind_tiny,   ind_tiny["close"])
        s_strong = scorer._score_momentum(ind_strong, ind_strong["close"])
        # Strong MACD hist should clearly outscore tiny hist.
        assert s_strong > s_tiny + 10.0

    def test_negative_macd_hist_penalised(self):
        ind_neg = make_ind(macd_hist=-0.10, rsi_14=60.0, macd_crossover_sessions_ago=999)
        ind_pos = make_ind(macd_hist=+0.10, rsi_14=60.0, macd_crossover_sessions_ago=999)
        s_neg = scorer._score_momentum(ind_neg, ind_neg["close"])
        s_pos = scorer._score_momentum(ind_pos, ind_pos["close"])
        assert s_pos > s_neg + 10.0


# ── Trend score (EMA200 slope) ────────────────────────────────────────────────

class TestTrendScore:
    def test_ema200_slope_does_not_saturate(self):
        """A modest 0.05% slope must NOT score the same as a strong 0.30% slope."""
        modest = scorer._score_trend(make_ind(ema200_slope=0.05))
        strong = scorer._score_trend(make_ind(ema200_slope=0.30))
        assert strong > modest + 5.0

    def test_zero_slope_low(self):
        s = scorer._score_trend(make_ind(ema200_slope=0.0))
        # Slope 0 should not contribute meaningfully — the rest of trend is fine,
        # so score is bounded but the slope sub-score itself contributes near zero.
        s_strong = scorer._score_trend(make_ind(ema200_slope=0.50))
        assert s_strong > s + 5.0


# ── Pattern score (Stage 2 graduated) ─────────────────────────────────────────

class TestStage2Graduated:
    def _ind_with_stage2(self, ema=False, near=False, obv=False, adx=False):
        return make_ind(
            ema_aligned=ema,
            near_52w_high=near,
            obv_trend="rising" if obv else "flat",
            adx_trending=adx,
            vcp_score=0.0, squeeze_score=0.0,  # isolate stage2
        )

    def test_zero_conditions_zero_score(self):
        s = scorer._score_stage2(self._ind_with_stage2())
        assert s == 0.0

    def test_two_conditions_partial_credit(self):
        s = scorer._score_stage2(self._ind_with_stage2(ema=True, near=True))
        assert 25.0 <= s <= 75.0  # not all-or-nothing

    def test_all_four_conditions_full_credit(self):
        s = scorer._score_stage2(self._ind_with_stage2(ema=True, near=True, obv=True, adx=True))
        assert s == 100.0

    def test_three_conditions_more_than_two(self):
        s2 = scorer._score_stage2(self._ind_with_stage2(ema=True, near=True))
        s3 = scorer._score_stage2(self._ind_with_stage2(ema=True, near=True, obv=True))
        assert s3 > s2


# ── End-to-end composite for the bad picks from the audit ─────────────────────

class TestAuditedBadPicks:
    """Reality check: the picks the user flagged should now score significantly lower."""

    def test_dht_like_flat_stock_scores_low(self):
        """Stock with no trend (ADX 15), neutral volume (1.14x), negative CMF —
        should not finish in the high 70s."""
        dht_like = make_ind(
            close=19.02, avg_volume_20d=3_220_345,
            adx_14=15.41, adx_trending=False,
            cmf_20=-0.023, volume_ratio=1.14,
            macd_hist=0.0804, macd_crossover_sessions_ago=5,
            ema200_slope=0.207, rsi_14=59.65,
            dist_from_52w_high_pct=7.45, pct_above_52w_low=83.7,
            vcp_score=21.8, squeeze_score=100.0,
            obv_trend="rising", obv_slope_norm=3.0, upvol_ratio=0.5,
            near_52w_high=True,
        )
        composite = scorer.compute_composite_score(dht_like)["composite_score"]
        assert composite < 70.0, f"DHT-like stock scored {composite}; should be under 70"

    def test_thin_microcap_scores_low(self):
        """EWCZ-like: $5.82 small-cap with $4M dollar volume — should be filtered out."""
        ewcz_like = make_ind(
            close=5.82, avg_volume_20d=681_055,        # ~$4M/day
            ema21=5.80, ema50=5.63, ema150=5.07, ema200=5.04,
            adx_14=56.07, adx_trending=True,
            cmf_20=-0.018, volume_ratio=8.32,
            ema200_slope=0.146, rsi_14=61.9,
            dist_from_52w_high_pct=10.67,
        )
        # Should not pass the dollar-volume hard filter
        assert scorer.passes_hard_filters(ewcz_like) is False
