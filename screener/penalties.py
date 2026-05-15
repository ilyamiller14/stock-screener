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

    # 3. Rally concentration
    conc = ind.get("concentration_60d", 0.0)
    if conc >= config.CONCENTRATION_60D_SEVERE_PCT:
        multipliers["concentration"] = 0.30
        triggered.append("concentration_severe")
    elif conc >= config.CONCENTRATION_60D_MILD_PCT:
        multipliers["concentration"] = 0.60
        triggered.append("concentration_mild")

    # 4. Recent reversal
    rev = ind.get("dist_from_5d_high_pct", 0.0)
    if rev >= config.REVERSAL_5D_HEAVY_PCT:
        multipliers["reversal"] = 0.40
        triggered.append("reversal_heavy")
    elif rev >= config.REVERSAL_5D_MILD_PCT:
        multipliers["reversal"] = 0.70
        triggered.append("reversal_mild")

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
