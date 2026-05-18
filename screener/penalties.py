"""
Tier 3 — Penalty Multipliers.

Each penalty is a (trigger condition, multiplier) pair. When triggered, the
penalty's multiplier is composed via min() with the final multiplier. Floor 0.05.
"""
from __future__ import annotations

from typing import Any

from . import config


_FLOOR = 0.05


def compute_penalty_multiplier(ind: dict[str, Any]) -> dict[str, Any]:
    """
    Returns:
      {
        "final_multiplier": float (>= 0.05),
        "triggered":        list[str],
        "multipliers":      dict[str, float],
      }
    """
    multipliers: dict[str, float] = {}
    triggered: list[str] = []

    # 1. Climactic single bar
    move = ind.get("max_1d_move_120d", 0.0)
    if move >= config.CLIMACTIC_1D_SEVERE_PCT:
        multipliers["climactic"] = 0.25
        triggered.append("climactic_severe")
    elif move >= config.CLIMACTIC_1D_HEAVY_PCT:
        multipliers["climactic"] = 0.50
        triggered.append("climactic_heavy")
    elif move >= config.CLIMACTIC_1D_MILD_PCT:
        multipliers["climactic"] = 0.85
        triggered.append("climactic_mild")

    # 2. Exhaustion gap
    gap = ind.get("max_gap_120d", 0.0)
    if gap >= config.GAP_PENALTY_HEAVY_PCT:
        multipliers["exhaustion_gap"] = 0.40
        triggered.append("exhaustion_gap_heavy")
    elif gap >= config.GAP_PENALTY_MILD_PCT:
        multipliers["exhaustion_gap"] = 0.80
        triggered.append("exhaustion_gap_mild")

    # 3. Rally concentration — v2.1: use MAX of 20/60/120-day windows so that
    # a recent climactic cluster (CPRX) or a mid-window spike (CWAN) can't hide
    # in a single window where they get diluted.
    conc = max(
        ind.get("concentration_20d",  0.0),
        ind.get("concentration_60d",  0.0),
        ind.get("concentration_120d", 0.0),
    )
    if conc >= config.CONCENTRATION_SEVERE_PCT:
        multipliers["concentration"] = 0.30
        triggered.append("concentration_severe")
    elif conc >= config.CONCENTRATION_MILD_PCT:
        multipliers["concentration"] = 0.60
        triggered.append("concentration_mild")

    # 3b. Wide-spread wide-range bar (NEW v2.1). Intraday H-L vs prev close.
    # CPRX April 27 was 19.2% range — that's textbook climactic action even
    # though close-to-close was only +6.9%.
    rng = ind.get("max_range_120d", 0.0)
    if rng >= config.WSWR_RANGE_HEAVY_PCT:
        multipliers["wswr"] = 0.40
        triggered.append("wswr_heavy")
    elif rng >= config.WSWR_RANGE_MILD_PCT:
        multipliers["wswr"] = 0.75
        triggered.append("wswr_mild")

    # 4. Recent reversal
    rev = ind.get("dist_from_5d_high_pct", 0.0)
    if rev >= config.REVERSAL_5D_HEAVY_PCT:
        multipliers["reversal"] = 0.40
        triggered.append("reversal_heavy")
    elif rev >= config.REVERSAL_5D_MILD_PCT:
        multipliers["reversal"] = 0.70
        triggered.append("reversal_mild")

    # 4b. Stale rally — v2.2 catches CSGS-style post-news drift where 1y return
    # was driven by a months-old spike and recent 60d is essentially flat.
    # Note: default rally_freshness_pct=100 means "fresh / no penalty".
    freshness = ind.get("rally_freshness_pct", 100.0)
    if freshness <= config.STALE_RALLY_HEAVY_PCT:
        multipliers["stale_rally"] = 0.40
        triggered.append("stale_rally_heavy")
    elif freshness <= config.STALE_RALLY_MILD_PCT:
        multipliers["stale_rally"] = 0.70
        triggered.append("stale_rally_mild")

    # 5. 52w-low extension
    above = ind.get("pct_above_52w_low", 0.0)
    if above >= config.DIST_52W_LOW_REJECT_PCT:
        multipliers["52w_low"] = 0.30
        triggered.append("52w_low_severe")
    elif above >= config.DIST_52W_LOW_HEAVY_PCT:
        multipliers["52w_low"] = 0.60
        triggered.append("52w_low_heavy")
    elif above >= config.DIST_52W_LOW_MILD_PCT:
        multipliers["52w_low"] = 0.85
        triggered.append("52w_low_mild")

    # 6. ATR extension (legacy thresholds preserved)
    atr_mult_x = ind.get("extension_atr_multiple", 0.0)
    if atr_mult_x >= config.EXTENSION_ATR_REJECT:
        multipliers["atr_extension"] = 0.10
        triggered.append("atr_extension_reject")
    elif atr_mult_x >= config.EXTENSION_ATR_HEAVY:
        multipliers["atr_extension"] = 0.50
        triggered.append("atr_extension_heavy")
    elif atr_mult_x >= config.EXTENSION_ATR_MILD:
        multipliers["atr_extension"] = 0.85
        triggered.append("atr_extension_mild")

    final = 1.0
    for m_ in multipliers.values():
        final = min(final, m_)
    final = max(_FLOOR, final)

    return {
        "final_multiplier": round(final, 3),
        "triggered":        triggered,
        "multipliers":      multipliers,
    }
