"""
Tier 2 — Setup Quality Score.

Five categories: Trend Strength, Trend Cleanliness, Relative Strength,
Base/Setup, Volume Profile. Each is graded 0-100; the composite is a weighted
sum using config.CATEGORY_WEIGHTS.
"""
from __future__ import annotations

from typing import Any

from . import config


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ── A. Trend Strength ─────────────────────────────────────────────────────────

def score_trend_strength(ind: dict[str, Any]) -> float:
    w = config.TREND_STRENGTH_SUB_WEIGHTS

    ema_align = 100.0 if ind.get("ema_aligned", False) else 0.0

    slope = ind.get("ema200_slope", 0.0)
    rising = ind.get("ema200_rising_sessions", 0) >= config.MIN_EMA200_RISING_SESSIONS
    slope_score = _clamp(slope * 350.0) if rising else _clamp(slope * 350.0) * 0.5

    ema50 = ind.get("ema50", 0.0)
    ema200 = ind.get("ema200", 0.0)
    if ema200 > 0:
        spread_score = _clamp((ema50 / ema200 - 1.0) * 500.0)
    else:
        spread_score = 0.0

    dist = ind.get("dist_from_52w_high_pct", 100.0)
    dist_score = _clamp(100.0 - dist * 4.0)

    adx_robust = ind.get("adx_robust", ind.get("adx_14", 0.0))
    adx_score = _clamp(adx_robust * 2.0)

    return (
        ema_align     * w["ema_alignment"]
        + slope_score   * w["ema200_slope_sustained"]
        + spread_score  * w["ema50_above_ema200"]
        + dist_score    * w["dist_from_52w_high"]
        + adx_score     * w["adx_robust"]
    )


# ── B. Trend Cleanliness ──────────────────────────────────────────────────────

def score_trend_cleanliness(ind: dict[str, Any]) -> float:
    w = config.TREND_CLEANLINESS_SUB_WEIGHTS
    r2 = ind.get("r2_log_60d", 0.0)
    r2_score = _clamp((r2 - 0.40) * 200.0)

    outliers = ind.get("outlier_bar_count_60d", 0)
    outlier_score = _clamp(100.0 - outliers * 25.0)

    return r2_score * w["r2_log_60d"] + outlier_score * w["outlier_bar_ratio"]


# ── C. Relative Strength ──────────────────────────────────────────────────────

def score_rs(ind: dict[str, Any]) -> float:
    w = config.RS_SUB_WEIGHTS
    ibd  = ind.get("ibd_rs_percentile", 50.0)
    p3m  = ind.get("rs_3m_percentile",  50.0)
    p6m  = ind.get("rs_6m_percentile",  50.0)
    p12m = ind.get("rs_12m_percentile", 50.0)
    base = (
        ibd  * w["ibd_rs_percentile"]
        + p3m  * w["rs_3m_percentile"]
        + p6m  * w["rs_6m_percentile"]
        + p12m * w["rs_12m_percentile"]
    )
    if ind.get("rs_line_at_50d_high", False):
        base += config.RS_LINE_NEW_HIGH_BONUS
    return _clamp(base)


# ── D. Base / Setup Quality ───────────────────────────────────────────────────

def _vcp_guarded_score(ind: dict[str, Any]) -> float:
    max_1d  = ind.get("max_1d_move_120d", 0.0)
    max_gap = ind.get("max_gap_120d", 0.0)
    if max_1d > config.VCP_GUARD_MAX_BAR_PCT or max_gap > config.VCP_GUARD_MAX_GAP_PCT:
        return 0.0
    return _clamp(ind.get("vcp_score", 0.0))


def _pivot_proximity_score(ind: dict[str, Any]) -> float:
    pivot = ind.get("pivot_price", 0.0)
    if pivot <= 0:
        return 0.0
    d = ind.get("dist_from_pivot_pct", 99.0)
    return _clamp(100.0 - abs(d - 0.5) * 20.0)


def score_base_setup(ind: dict[str, Any]) -> float:
    w = config.BASE_SETUP_SUB_WEIGHTS
    vcp     = _vcp_guarded_score(ind)
    pivot   = _pivot_proximity_score(ind)
    squeeze = _clamp(ind.get("squeeze_score", 0.0))
    return vcp * w["vcp_guarded"] + pivot * w["pivot_proximity"] + squeeze * w["squeeze"]


# ── E. Volume Profile ─────────────────────────────────────────────────────────

def score_volume_profile(ind: dict[str, Any]) -> float:
    w = config.VOLUME_PROFILE_SUB_WEIGHTS

    obv_slope = ind.get("obv_slope_norm", 0.0)
    obv_score = _clamp((obv_slope + 10.0) * 5.0)

    cmf = ind.get("cmf_20", 0.0)
    cmf_score = _clamp((cmf + 0.2) * 100.0)

    pull = ind.get("pullback_vol_ratio", 1.0)
    dryup_score = _clamp((1.0 - pull) * 200.0)

    dist_p = ind.get("dist_from_pivot_pct", 99.0)
    vol_ratio = ind.get("volume_ratio", 1.0)
    if -2.0 <= dist_p <= 2.0 and ind.get("pivot_price", 0.0) > 0:
        breakout_score = _clamp(50.0 + (vol_ratio - 1.0) * 50.0)
    else:
        breakout_score = 50.0

    return (
        obv_score        * w["obv_slope"]
        + cmf_score        * w["cmf"]
        + dryup_score      * w["pullback_vol_dryup"]
        + breakout_score   * w["breakout_day_volume"]
    )


# ── Composite ─────────────────────────────────────────────────────────────────

def compute_setup_score(ind: dict[str, Any]) -> dict[str, float]:
    """Return per-category scores plus the weighted raw setup score (0-100)."""
    ts = score_trend_strength(ind)
    tc = score_trend_cleanliness(ind)
    rs = score_rs(ind)
    bs = score_base_setup(ind)
    vp = score_volume_profile(ind)
    w = config.CATEGORY_WEIGHTS
    total = (
        ts * w["trend_strength"]
        + tc * w["trend_cleanliness"]
        + rs * w["rs"]
        + bs * w["base_setup"]
        + vp * w["volume_profile"]
    )
    return {
        "trend_strength":    round(ts, 1),
        "trend_cleanliness": round(tc, 1),
        "rs":                round(rs, 1),
        "base_setup":        round(bs, 1),
        "volume_profile":    round(vp, 1),
        "raw_setup_score":   round(total, 1),
    }
