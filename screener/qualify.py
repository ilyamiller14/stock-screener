"""
Tier 1 — Qualification Gate.

A stock must pass ALL criteria here to reach Tier 2 scoring. Failures are
final (no graduated penalty).
"""
from __future__ import annotations

from typing import Any

from . import config


def qualifies(ind: dict[str, Any]) -> tuple[bool, str]:
    """
    Return (True, "") if the stock passes every Tier 1 criterion.
    Return (False, "<short reason>") otherwise, naming the FIRST failing criterion.
    """
    close   = ind.get("close", 0.0)
    avg_vol = ind.get("avg_volume_20d", 0)

    if close < config.MIN_PRICE:
        return False, f"price<{config.MIN_PRICE}"
    if avg_vol < config.MIN_AVG_VOLUME:
        return False, f"avg_vol<{config.MIN_AVG_VOLUME}"
    if close * avg_vol < config.MIN_DOLLAR_VOLUME:
        return False, f"dollar_vol<{config.MIN_DOLLAR_VOLUME}"

    if not ind.get("ema_aligned", False):
        return False, "ema_aligned=false"

    ema50  = ind.get("ema50",  0.0)
    ema150 = ind.get("ema150", 0.0)
    ema200 = ind.get("ema200", 0.0)
    if not (ema50 > ema150 > ema200 > 0):
        return False, "ema_order"

    if ind.get("ema200_rising_sessions", 0) < config.MIN_EMA200_RISING_SESSIONS:
        return False, f"ema200_rising_sessions<{config.MIN_EMA200_RISING_SESSIONS}"

    if ind.get("dist_from_52w_high_pct", 100.0) > config.MAX_DIST_FROM_52W_HIGH_PCT:
        return False, "dist_from_52w_high>25"

    if ind.get("pct_above_52w_low", 0.0) < config.MIN_PCT_ABOVE_52W_LOW:
        return False, "pct_above_52w_low<30"

    if ind.get("adx_14", 0.0) < config.MIN_ADX:
        return False, f"adx<{config.MIN_ADX}"

    if ind.get("max_1d_move_120d", 0.0) >= config.HARD_REJECT_1D_MOVE_PCT:
        return False, f"climactic_1d_move>={config.HARD_REJECT_1D_MOVE_PCT}"
    if ind.get("max_gap_120d", 0.0) >= config.HARD_REJECT_GAP_PCT:
        return False, f"exhaustion_gap>={config.HARD_REJECT_GAP_PCT}"

    if ind.get("vol_60d", 0.0) > config.HARD_REJECT_VOL_60D_PCT:
        return False, f"vol_60d>{config.HARD_REJECT_VOL_60D_PCT}"

    return True, ""
