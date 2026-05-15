"""
Tests for new v2 indicators added to screener.indicators.
The OHLCV-dependent functions are tested via small synthetic DataFrames.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _make_df(closes, opens=None, highs=None, lows=None, volumes=None):
    """Build a minimal OHLCV DataFrame from a list of closes."""
    n = len(closes)
    closes = np.asarray(closes, dtype=float)
    opens   = np.asarray(opens   if opens   is not None else closes, dtype=float)
    highs   = np.asarray(highs   if highs   is not None else closes * 1.005, dtype=float)
    lows    = np.asarray(lows    if lows    is not None else closes * 0.995, dtype=float)
    volumes = np.asarray(volumes if volumes is not None else np.ones(n) * 1_000_000, dtype=float)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=idx,
    )


# ── ema200_rising_sessions ────────────────────────────────────────────────────

class TestEma200RisingSessions:
    def test_rising_for_full_window(self):
        from screener.indicators import compute_ema200_rising_sessions
        df = _make_df(np.linspace(10, 50, 250))
        result = compute_ema200_rising_sessions(df)
        assert result["ema200_rising_sessions"] >= 22

    def test_flat_returns_zero(self):
        from screener.indicators import compute_ema200_rising_sessions
        df = _make_df([20.0] * 250)
        result = compute_ema200_rising_sessions(df)
        assert result["ema200_rising_sessions"] == 0

    def test_recently_turned_up_returns_small_count(self):
        from screener.indicators import compute_ema200_rising_sessions
        closes = np.concatenate([np.full(240, 20.0), np.linspace(20, 25, 10)])
        df = _make_df(closes)
        result = compute_ema200_rising_sessions(df)
        assert 0 < result["ema200_rising_sessions"] < 22
