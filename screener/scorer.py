"""
Score and rank all Russell 2000 stocks.

Pipeline:
1. Apply hard filter gate (discard non-qualifying stocks)
2. Compute RS percentiles across qualifying universe
3. Score each qualifying stock (0–100 composite)
4. Apply sector diversification cap
5. Return top N picks
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import yfinance as yf

from . import config

logger = logging.getLogger(__name__)


# ── Hard filter gate ──────────────────────────────────────────────────────────

def passes_hard_filters(ind: dict[str, Any]) -> bool:
    """Return True if the stock passes all Stage 2 prerequisite filters."""
    close   = ind.get("close", 0.0)
    avg_vol = ind.get("avg_volume_20d", 0)
    ema200  = ind.get("ema200", None)
    slope_pos = ind.get("ema200_slope_positive", False)

    if close < config.MIN_PRICE:
        return False
    if avg_vol < config.MIN_AVG_VOLUME:
        return False
    if ema200 is None or close <= ema200:
        return False
    if not slope_pos:
        return False
    return True


# ── RS percentile computation ─────────────────────────────────────────────────

def compute_rs_percentiles(
    all_indicators: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    """
    Compute RS percentiles for each stock within the qualifying universe.
    Includes standard 3m/6m RS and IBD-style quarter-weighted RS.
    """
    tickers    = [i["ticker"] for i in all_indicators]
    rs_3m_raw  = np.array([i.get("rs_raw_63d", 0.0) for i in all_indicators])
    rs_6m_raw  = np.array([i.get("rs_raw_126d", 0.0) for i in all_indicators])
    ibd_rs_raw = np.array([i.get("ibd_rs_raw", 0.0) for i in all_indicators])

    n = len(tickers)
    if n == 0:
        return {}

    def _percentile_ranks(values: np.ndarray) -> np.ndarray:
        ranks = np.zeros(n)
        for i, v in enumerate(values):
            ranks[i] = float(np.sum(values < v)) / (n - 1) * 100 if n > 1 else 50.0
        return ranks

    p3m  = _percentile_ranks(rs_3m_raw)
    p6m  = _percentile_ranks(rs_6m_raw)
    pibd = _percentile_ranks(ibd_rs_raw)

    return {
        tickers[i]: {
            "rs_3m_percentile":  round(float(p3m[i]),  1),
            "rs_6m_percentile":  round(float(p6m[i]),  1),
            "ibd_rs_percentile": round(float(pibd[i]), 1),
        }
        for i in range(n)
    }


# ── Sub-score helpers ─────────────────────────────────────────────────────────

def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


def _score_trend(ind: dict[str, Any]) -> float:
    # EMA alignment: binary 0/100
    ema_align_score = 100.0 if ind.get("ema_aligned", False) else 0.0

    # EMA_200 slope: normalise daily % slope (0.04% per day is good)
    slope = ind.get("ema200_slope", 0.0)
    ema200_slope_score = _clamp(slope * 2500.0)  # 0.04 → 100

    # Distance from 52W high: closer is better
    dist = ind.get("dist_from_52w_high_pct", 100.0)
    dist_score = _clamp(100.0 - dist * config.DIST_52W_HIGH_SCALE)

    # ADX: scale by ADX_SCALE
    adx = ind.get("adx_14", 0.0)
    adx_score = _clamp(adx * config.ADX_SCALE)

    w = config.TREND_SUB_WEIGHTS
    return (
        ema_align_score    * w["ema_alignment"]
        + ema200_slope_score * w["ema200_slope"]
        + dist_score         * w["dist_from_52w_high"]
        + adx_score          * w["adx"]
    )


def _score_rs(ind: dict[str, Any]) -> float:
    ibd = ind.get("ibd_rs_percentile", 50.0)
    p3m = ind.get("rs_3m_percentile", 50.0)
    p6m = ind.get("rs_6m_percentile", 50.0)
    w = config.RS_SUB_WEIGHTS
    return ibd * w["ibd_rs_percentile"] + p3m * w["rs_3m_percentile"] + p6m * w["rs_6m_percentile"]


def _score_volume(ind: dict[str, Any]) -> float:
    # OBV slope: normalised, positive → high score
    obv_slope = ind.get("obv_slope_norm", 0.0)
    obv_score = _clamp((obv_slope + 10.0) * 5.0)  # -10..+10 → 0..100

    # CMF: map -1..1 → 0..100
    cmf = ind.get("cmf_20", 0.0)
    cmf_score = _clamp((cmf + 1.0) / 2.0 * 100.0)

    # Up-day volume ratio: 0..1 → 0..100
    upvol = ind.get("upvol_ratio", 0.5)
    upvol_score = _clamp(upvol * 100.0)

    w = config.VOLUME_SUB_WEIGHTS
    return (
        obv_score   * w["obv_slope"]
        + cmf_score   * w["cmf"]
        + upvol_score * w["upvol_ratio"]
    )


def _score_momentum(ind: dict[str, Any], close: float) -> float:
    # RSI: ideal is 60, penalise deviation
    rsi = ind.get("rsi_14", 50.0)
    rsi_score = _clamp(100.0 - abs(rsi - config.RSI_IDEAL) * config.RSI_SCORE_DECAY)

    # MACD histogram: positive and expanding
    macd_hist = ind.get("macd_hist", 0.0)
    if close > 0:
        hist_norm = macd_hist / close * 10000.0  # normalise to price
    else:
        hist_norm = 0.0
    macd_hist_score = _clamp((hist_norm + 5.0) * 10.0)  # -5..+5 → 0..100

    # MACD crossover recency
    sessions_ago = ind.get("macd_crossover_sessions_ago", 999)
    if sessions_ago <= config.MACD_CROSSOVER_MAX_SESSIONS:
        crossover_score = 100.0
    elif sessions_ago >= config.MACD_CROSSOVER_DECAY_SESSIONS:
        crossover_score = 0.0
    else:
        decay_range = config.MACD_CROSSOVER_DECAY_SESSIONS - config.MACD_CROSSOVER_MAX_SESSIONS
        crossover_score = (1.0 - (sessions_ago - config.MACD_CROSSOVER_MAX_SESSIONS) / decay_range) * 100.0

    w = config.MOMENTUM_SUB_WEIGHTS
    return (
        rsi_score        * w["rsi"]
        + macd_hist_score  * w["macd_hist"]
        + crossover_score  * w["macd_crossover"]
    )


def _score_stage2(ind: dict[str, Any]) -> float:
    """Full Weinstein Stage 2 check: EMA aligned, near 52W high, OBV rising, ADX trending."""
    ema_ok  = ind.get("ema_aligned", False)
    near_hh = ind.get("near_52w_high", False)
    obv_ok  = ind.get("obv_trend", "flat") == "rising"
    adx_ok  = ind.get("adx_trending", False)
    return 100.0 if (ema_ok and near_hh and obv_ok and adx_ok) else 0.0


def _score_pattern(ind: dict[str, Any]) -> float:
    """
    Pattern quality score: VCP + Keltner/BB Squeeze + Stage 2.
    Rewards stocks with identifiable base patterns and volatility contraction.
    """
    vcp_score     = _clamp(ind.get("vcp_score", 0.0))
    squeeze_score = _clamp(ind.get("squeeze_score", 0.0))
    stage2_score  = _score_stage2(ind)

    w = config.PATTERN_SUB_WEIGHTS
    return (
        vcp_score     * w["vcp"]
        + squeeze_score * w["squeeze"]
        + stage2_score  * w["stage2"]
    )


def compute_composite_score(ind: dict[str, Any]) -> dict[str, float]:
    """Return composite score and per-category breakdown."""
    close = ind.get("close", 1.0)

    trend_s    = _score_trend(ind)
    rs_s       = _score_rs(ind)
    volume_s   = _score_volume(ind)
    momentum_s = _score_momentum(ind, close)
    pattern_s  = _score_pattern(ind)

    w = config.CATEGORY_WEIGHTS
    composite = (
        trend_s    * w["trend"]
        + rs_s       * w["rs"]
        + volume_s   * w["volume"]
        + momentum_s * w["momentum"]
        + pattern_s  * w["pattern"]
    )

    return {
        "composite_score": round(composite, 1),
        "trend_score":     round(trend_s, 1),
        "rs_score":        round(rs_s, 1),
        "volume_score":    round(volume_s, 1),
        "momentum_score":  round(momentum_s, 1),
        "pattern_score":   round(pattern_s, 1),
    }


# ── Sector info ───────────────────────────────────────────────────────────────

def fetch_sector_info(tickers: list[str]) -> dict[str, str]:
    """
    Fetch sector + company name for a small list of tickers.
    Only called for final top-30 candidates (not all 2000 — too slow).
    """
    info: dict[str, str] = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            data = t.info
            info[ticker] = {
                "company_name": data.get("longName") or data.get("shortName") or ticker,
                "sector":       data.get("sector") or "Unknown",
                "industry":     data.get("industry") or "Unknown",
            }
        except Exception:
            info[ticker] = {
                "company_name": ticker,
                "sector":       "Unknown",
                "industry":     "Unknown",
            }
    return info


# ── Main ranking function ─────────────────────────────────────────────────────

def rank_stocks(
    all_indicators: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Full pipeline: filter → percentile → score → diversify → top N.

    Returns:
        (top_picks, stats_dict)
        top_picks: list of enriched indicator dicts for top N stocks
        stats_dict: run statistics (screened_count, qualifying_count, etc.)
    """
    screened_count = len(all_indicators)
    logger.info("Screening %d tickers...", screened_count)

    # 1. Hard filter gate
    qualifying = [ind for ind in all_indicators if passes_hard_filters(ind)]
    qualifying_count = len(qualifying)
    logger.info("Qualifying (passed hard filters): %d", qualifying_count)

    if qualifying_count == 0:
        return [], {"screened_count": screened_count, "qualifying_count": 0}

    # 2. RS percentiles within qualifying universe
    percentiles = compute_rs_percentiles(qualifying)
    for ind in qualifying:
        ticker = ind["ticker"]
        ind.update(percentiles.get(ticker, {"rs_3m_percentile": 50.0, "rs_6m_percentile": 50.0, "ibd_rs_percentile": 50.0}))

    # 3. Composite score
    for ind in qualifying:
        scores = compute_composite_score(ind)
        ind.update(scores)

    # 4. Sort descending by composite score
    qualifying.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)

    # 5. Sector diversification: take top N, capping per sector
    # Fetch sector info for top 30 candidates only
    candidate_tickers = [i["ticker"] for i in qualifying[:30]]
    logger.info("Fetching sector info for %d candidates...", len(candidate_tickers))
    sector_info = fetch_sector_info(candidate_tickers)

    top_picks: list[dict[str, Any]] = []
    sector_counts: dict[str, int] = {}

    for ind in qualifying:
        if len(top_picks) >= config.TOP_N:
            break
        ticker = ind["ticker"]
        meta   = sector_info.get(ticker, {"sector": "Unknown", "company_name": ticker, "industry": "Unknown"})
        sector = meta["sector"]
        if sector_counts.get(sector, 0) >= config.MAX_PICKS_PER_SECTOR:
            continue
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        ind.update(meta)
        top_picks.append(ind)

    logger.info("Top picks selected: %d", len(top_picks))

    stats = {
        "screened_count":   screened_count,
        "qualifying_count": qualifying_count,
    }
    return top_picks, stats
