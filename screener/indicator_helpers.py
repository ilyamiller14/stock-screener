"""
Pure-Python helpers used by indicators.py.

Kept separate so they can be unit-tested without pulling in pandas_ta /
numba (which are heavy and platform-finicky).
"""
from __future__ import annotations


def squeeze_score(
    *,
    squeeze_on: bool,
    squeeze_fired: bool,
    squeeze_bars: int,
    bullish_direction: bool,
) -> float:
    """
    Score the squeeze state, taking breakout direction into account.

    A bullish-direction "fire" is the actionable signal worth 100. A bearish
    fire (BB exited KC while price is below the middle band) is a failed
    squeeze and gets only partial credit. An "on" squeeze rewards duration.
    """
    if squeeze_fired:
        return 100.0 if bullish_direction else 25.0
    if squeeze_on:
        # Currently squeezing — reward duration (longer = building energy)
        # If price is below the middle band, dampen.
        base = min(80.0, squeeze_bars * 5.0)
        return base if bullish_direction else base * 0.5
    return 0.0


def is_valid_vcp(
    *,
    vcp_score: float,
    tightening_count: int,
    n_contractions: int,
) -> bool:
    """
    Tighter VCP detection criteria — based on Minervini's textbook pattern:
    - vcp_score must reach a meaningful threshold (50, not 40)
    - At least 2 progressively tighter contractions (not 1)
    - Between 2 and 6 contractions total — more than 6 = sloppy noise
    """
    return (
        vcp_score >= 50.0
        and tightening_count >= 2
        and 2 <= n_contractions <= 6
    )
