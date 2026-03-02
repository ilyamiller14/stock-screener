"""
Compute all technical indicators from raw OHLCV data.

All indicators are computed from first principles using pandas + pandas_ta.
No vendor-supplied pre-computed values.

Returns a flat dict of indicator values for each ticker — this is what
scorer.py consumes.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import pandas_ta as ta
from scipy import stats

from . import config

logger = logging.getLogger(__name__)


# ── EMAs ──────────────────────────────────────────────────────────────────────

def compute_emas(df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA_21, EMA_50, EMA_150, EMA_200 columns."""
    close = df["Close"].squeeze()
    for period in (21, 50, 150, 200):
        df[f"EMA_{period}"] = ta.ema(close, length=period)
    return df


def compute_ema_alignment(df: pd.DataFrame) -> dict[str, Any]:
    """
    Stage 2 EMA alignment check.
    Returns:
      - ema_aligned: True if Close > EMA_21 > EMA_50 > EMA_150 > EMA_200
      - ema200_slope: slope of EMA_200 over last N sessions (as % of price per day)
      - ema200_slope_positive: True if slope > threshold
    """
    last = df.iloc[-1]
    close = float(last["Close"])
    e21   = float(last["EMA_21"])   if not pd.isna(last.get("EMA_21"))   else None
    e50   = float(last["EMA_50"])   if not pd.isna(last.get("EMA_50"))   else None
    e150  = float(last["EMA_150"])  if not pd.isna(last.get("EMA_150"))  else None
    e200  = float(last["EMA_200"])  if not pd.isna(last.get("EMA_200"))  else None

    if any(v is None for v in (e21, e50, e150, e200)):
        return {"ema_aligned": False, "ema200_slope": 0.0, "ema200_slope_positive": False}

    ema_aligned = close > e21 > e50 > e150 > e200  # type: ignore[operator]

    # EMA_200 slope: linear regression over last N sessions
    n = config.MIN_EMA200_SLOPE_SESSIONS
    ema200_series = df["EMA_200"].dropna().tail(n)
    if len(ema200_series) >= n // 2:
        x = np.arange(len(ema200_series))
        slope, _, _, _, _ = stats.linregress(x, ema200_series.values)
        # Normalise to % of price per day
        ema200_slope = float(slope / close * 100) if close > 0 else 0.0
    else:
        ema200_slope = 0.0

    return {
        "ema_aligned": bool(ema_aligned),
        "ema21":  round(e21, 4),
        "ema50":  round(e50, 4),
        "ema150": round(e150, 4),
        "ema200": round(e200, 4),
        "ema200_slope": round(ema200_slope, 6),
        "ema200_slope_positive": ema200_slope > config.EMA200_SLOPE_THRESHOLD,
    }


# ── 52-week stats ──────────────────────────────────────────────────────────────

def compute_52w_stats(df: pd.DataFrame) -> dict[str, Any]:
    """Compute 52-week high/low and distance from high."""
    window = min(252, len(df))
    subset = df.tail(window)
    high_52w = float(subset["High"].max())
    low_52w  = float(subset["Low"].min())
    close    = float(df["Close"].iloc[-1])

    dist_from_high_pct = (high_52w - close) / high_52w * 100 if high_52w > 0 else 100.0
    pct_above_low      = (close - low_52w) / low_52w * 100   if low_52w  > 0 else 0.0

    return {
        "high_52w":               round(high_52w, 4),
        "low_52w":                round(low_52w,  4),
        "dist_from_52w_high_pct": round(dist_from_high_pct, 2),
        "pct_above_52w_low":      round(pct_above_low, 2),
        "near_52w_high":          dist_from_high_pct <= 25.0,
    }


# ── RSI ───────────────────────────────────────────────────────────────────────

def compute_rsi(df: pd.DataFrame, period: int = 14) -> dict[str, Any]:
    close = df["Close"].squeeze()
    rsi_series = ta.rsi(close, length=period)
    if rsi_series is None or rsi_series.empty:
        return {"rsi_14": 50.0}
    val = float(rsi_series.iloc[-1])
    return {"rsi_14": round(val, 2) if not np.isnan(val) else 50.0}


# ── MACD ──────────────────────────────────────────────────────────────────────

def compute_macd(df: pd.DataFrame) -> dict[str, Any]:
    close = df["Close"].squeeze()
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    if macd_df is None or macd_df.empty:
        return {
            "macd": 0.0, "macd_signal": 0.0, "macd_hist": 0.0,
            "macd_crossover_bullish": False, "macd_crossover_sessions_ago": 999,
        }

    # pandas_ta MACD column names: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
    macd_col   = [c for c in macd_df.columns if c.startswith("MACD_")]
    hist_col   = [c for c in macd_df.columns if c.startswith("MACDh_")]
    signal_col = [c for c in macd_df.columns if c.startswith("MACDs_")]

    def _last(series_list: list[str]) -> float:
        if not series_list:
            return 0.0
        v = macd_df[series_list[0]].iloc[-1]
        return float(v) if not np.isnan(v) else 0.0

    macd_val    = _last(macd_col)
    macd_hist   = _last(hist_col)
    macd_signal = _last(signal_col)

    # Detect bullish crossover (MACD crossed above signal) within last N sessions
    crossover_sessions_ago = 999
    if macd_col and signal_col:
        macd_series   = macd_df[macd_col[0]].fillna(0)
        signal_series = macd_df[signal_col[0]].fillna(0)
        diff = macd_series - signal_series
        tail = diff.tail(config.MACD_CROSSOVER_DECAY_SESSIONS)
        for i in range(1, len(tail)):
            if tail.iloc[i] > 0 and tail.iloc[i - 1] <= 0:
                crossover_sessions_ago = len(tail) - i - 1
                break

    return {
        "macd":                    round(macd_val, 4),
        "macd_signal":             round(macd_signal, 4),
        "macd_hist":               round(macd_hist, 4),
        "macd_crossover_bullish":  crossover_sessions_ago <= config.MACD_CROSSOVER_MAX_SESSIONS,
        "macd_crossover_sessions_ago": crossover_sessions_ago,
    }


# ── ADX ───────────────────────────────────────────────────────────────────────

def compute_adx(df: pd.DataFrame, period: int = 14) -> dict[str, Any]:
    adx_df = ta.adx(df["High"].squeeze(), df["Low"].squeeze(), df["Close"].squeeze(), length=period)
    if adx_df is None or adx_df.empty:
        return {"adx_14": 0.0, "adx_trending": False}

    adx_col = [c for c in adx_df.columns if c.startswith("ADX_")]
    dmp_col = [c for c in adx_df.columns if c.startswith("DMP_")]
    dmn_col = [c for c in adx_df.columns if c.startswith("DMN_")]

    def _last_col(cols: list[str]) -> float:
        if not cols:
            return 0.0
        v = adx_df[cols[0]].iloc[-1]
        return float(v) if not np.isnan(v) else 0.0

    adx_val = _last_col(adx_col)
    dmp_val = _last_col(dmp_col)
    dmn_val = _last_col(dmn_col)

    return {
        "adx_14":      round(adx_val, 2),
        "adx_dmp":     round(dmp_val, 2),
        "adx_dmn":     round(dmn_val, 2),
        "adx_trending": adx_val > 20.0 and dmp_val > dmn_val,
    }


# ── OBV ───────────────────────────────────────────────────────────────────────

def compute_obv(df: pd.DataFrame) -> dict[str, Any]:
    """
    On-Balance Volume. Compute slope of OBV over last 20 sessions to detect
    accumulation (positive slope) vs distribution (negative slope).
    Slope is normalised to % of price per day for cross-ticker comparability.
    """
    close  = df["Close"].squeeze()
    volume = df["Volume"].squeeze()
    direction = np.sign(close.diff().fillna(0))
    obv = (direction * volume).cumsum()

    last_obv = float(obv.iloc[-1])
    n = 20
    tail = obv.tail(n)
    close_tail = close.tail(n)
    close_mean = float(close_tail.mean()) if len(close_tail) > 0 else 1.0

    if len(tail) >= n // 2:
        x = np.arange(len(tail))
        slope, _, _, _, _ = stats.linregress(x, tail.values)
        # Normalise: slope per session as % of avg daily volume
        avg_vol = float(volume.tail(20).mean())
        obv_slope_norm = float(slope / avg_vol * 100) if avg_vol > 0 else 0.0
        # Also express as price-normalised slope
        obv_slope_price_norm = float(slope / close_mean / 1000) if close_mean > 0 else 0.0
    else:
        obv_slope_norm = 0.0
        obv_slope_price_norm = 0.0

    obv_trend = "rising" if obv_slope_norm > 1.0 else ("falling" if obv_slope_norm < -1.0 else "flat")

    return {
        "obv_last":            round(last_obv, 0),
        "obv_slope_norm":      round(obv_slope_norm, 4),
        "obv_slope_price_norm": round(obv_slope_price_norm, 6),
        "obv_trend":           obv_trend,
    }


# ── Chaikin Money Flow ────────────────────────────────────────────────────────

def compute_cmf(df: pd.DataFrame, period: int = 20) -> dict[str, Any]:
    """Chaikin Money Flow. Range -1 to +1. Positive = accumulation."""
    cmf_series = ta.cmf(
        df["High"].squeeze(),
        df["Low"].squeeze(),
        df["Close"].squeeze(),
        df["Volume"].squeeze(),
        length=period,
    )
    if cmf_series is None or cmf_series.empty:
        return {"cmf_20": 0.0}
    val = float(cmf_series.iloc[-1])
    return {"cmf_20": round(val, 4) if not np.isnan(val) else 0.0}


# ── Volume analysis ───────────────────────────────────────────────────────────

def compute_volume_analysis(df: pd.DataFrame) -> dict[str, Any]:
    """
    Volume metrics:
    - avg_volume_20d: 20-day average volume
    - volume_ratio: today's volume / avg_volume_20d
    - upvol_ratio: fraction of up-days with above-average volume (Weinstein confirmation)
    """
    volume = df["Volume"].squeeze()
    close  = df["Close"].squeeze()

    avg_vol_20 = float(volume.tail(20).mean())
    today_vol  = float(volume.iloc[-1])
    vol_ratio  = today_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0

    # Up-day volume ratio over last 50 sessions
    recent = df.tail(50).copy()
    recent["up_day"] = recent["Close"] > recent["Close"].shift(1)
    recent["above_avg_vol"] = recent["Volume"] > avg_vol_20
    up_days = recent[recent["up_day"] == True]
    if len(up_days) > 0:
        upvol_ratio = float(up_days["above_avg_vol"].sum() / len(up_days))
    else:
        upvol_ratio = 0.5

    return {
        "avg_volume_20d": int(avg_vol_20),
        "volume_today":   int(today_vol),
        "volume_ratio":   round(vol_ratio, 2),
        "upvol_ratio":    round(upvol_ratio, 3),
    }


# ── Relative Strength vs benchmark ───────────────────────────────────────────

def compute_relative_strength(
    ticker_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    periods: tuple[int, ...] = (63, 126),
) -> dict[str, Any]:
    """
    Compute raw RS as ticker return / benchmark return over each period.
    Percentile ranking is done later in scorer.py across the full universe.
    """
    results: dict[str, Any] = {}
    ticker_close    = ticker_df["Close"].squeeze()
    benchmark_close = benchmark_df["Close"].squeeze()

    for p in periods:
        t_tail = ticker_close.tail(p + 1)
        b_tail = benchmark_close.tail(p + 1)

        if len(t_tail) < p or len(b_tail) < p:
            results[f"rs_raw_{p}d"] = 0.0
            continue

        t_ret = float(t_tail.iloc[-1] / t_tail.iloc[0] - 1)
        b_ret = float(b_tail.iloc[-1] / b_tail.iloc[0] - 1)
        rs_raw = t_ret - b_ret
        results[f"rs_raw_{p}d"] = round(rs_raw, 6)

    return results


# ── IBD-Style Relative Strength ──────────────────────────────────────────────

def compute_ibd_rs(
    ticker_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
) -> dict[str, Any]:
    """
    IBD-style Relative Strength with quarter-weighted formula.
    RS = 0.4 * Q1_return + 0.2 * Q2_return + 0.2 * Q3_return + 0.2 * Q4_return
    where Q1 = most recent quarter (63 trading days).
    Double-weights recent performance to catch accelerating momentum.
    Percentile ranking is done in scorer.py across the full universe.
    """
    ticker_close    = ticker_df["Close"].squeeze()
    benchmark_close = benchmark_df["Close"].squeeze()

    # Quarter boundaries (trading days): Q1=0-63, Q2=63-126, Q3=126-189, Q4=189-252
    quarter_days = [63, 126, 189, 252]
    t_len = len(ticker_close)
    b_len = len(benchmark_close)

    if t_len < 252 or b_len < 252:
        # Fall back to simple 12-month return if insufficient data
        if t_len > 63 and b_len > 63:
            t_ret = float(ticker_close.iloc[-1] / ticker_close.iloc[-63] - 1)
            b_ret = float(benchmark_close.iloc[-1] / benchmark_close.iloc[-63] - 1)
            return {"ibd_rs_raw": round(t_ret - b_ret, 6)}
        return {"ibd_rs_raw": 0.0}

    # Compute quarterly returns for both ticker and benchmark
    t_q_returns = []
    b_q_returns = []
    for i, end in enumerate(quarter_days):
        start = quarter_days[i - 1] if i > 0 else 0
        t_start_price = float(ticker_close.iloc[-(end + 1)])
        t_end_price   = float(ticker_close.iloc[-(start + 1)]) if start > 0 else float(ticker_close.iloc[-1])
        b_start_price = float(benchmark_close.iloc[-(end + 1)])
        b_end_price   = float(benchmark_close.iloc[-(start + 1)]) if start > 0 else float(benchmark_close.iloc[-1])

        t_q_ret = (t_end_price / t_start_price - 1) if t_start_price > 0 else 0.0
        b_q_ret = (b_end_price / b_start_price - 1) if b_start_price > 0 else 0.0
        t_q_returns.append(t_q_ret)
        b_q_returns.append(b_q_ret)

    # IBD weighting: 2x most recent quarter, 1x each older quarter
    # Q1(recent)=0.4, Q2=0.2, Q3=0.2, Q4=0.2
    weights = [0.4, 0.2, 0.2, 0.2]
    t_weighted = sum(w * r for w, r in zip(weights, t_q_returns))
    b_weighted = sum(w * r for w, r in zip(weights, b_q_returns))

    ibd_rs_raw = t_weighted - b_weighted

    return {"ibd_rs_raw": round(ibd_rs_raw, 6)}


# ── VCP Detection (Volatility Contraction Pattern) ───────────────────────────

def compute_vcp(df: pd.DataFrame) -> dict[str, Any]:
    """
    Detect Volatility Contraction Pattern (Minervini/O'Neil).

    Algorithm:
    1. Look back over last 120 days for swing highs/lows
    2. Identify contractions (each pullback from a swing high to a swing low)
    3. Check if contractions are progressively shallower (50-60% smaller each time)
    4. Check if ATR is declining from base start to current
    5. Check if volume is drying up during the contraction

    Returns:
      - vcp_detected: True if a valid VCP pattern is found
      - vcp_contractions: number of contractions found (2-4 is ideal)
      - vcp_tightness: ratio of last contraction to first (lower = tighter)
      - vcp_atr_decline: ATR decline % from base start to current
      - vcp_vol_decline: volume decline % from base start to current
      - vcp_score: 0-100 composite VCP quality score
    """
    default = {
        "vcp_detected": False, "vcp_contractions": 0, "vcp_tightness": 1.0,
        "vcp_atr_decline": 0.0, "vcp_vol_decline": 0.0, "vcp_score": 0.0,
    }

    close  = df["Close"].squeeze()
    high   = df["High"].squeeze()
    low    = df["Low"].squeeze()
    volume = df["Volume"].squeeze()

    lookback = min(120, len(df) - 1)
    if lookback < 40:
        return default

    recent = df.tail(lookback).copy()
    r_close = recent["Close"].values.astype(float)
    r_high  = recent["High"].values.astype(float)
    r_low   = recent["Low"].values.astype(float)
    r_vol   = recent["Volume"].values.astype(float)

    # Find swing highs and lows using a 5-bar pivot
    pivot = 5
    swing_highs: list[tuple[int, float]] = []  # (index, price)
    swing_lows:  list[tuple[int, float]] = []

    for i in range(pivot, lookback - pivot):
        # Swing high: higher than pivot bars on both sides
        if r_high[i] == max(r_high[i - pivot : i + pivot + 1]):
            swing_highs.append((i, float(r_high[i])))
        # Swing low: lower than pivot bars on both sides
        if r_low[i] == min(r_low[i - pivot : i + pivot + 1]):
            swing_lows.append((i, float(r_low[i])))

    if len(swing_highs) < 2 or len(swing_lows) < 1:
        return default

    # Measure contractions: distance from each swing high to the next swing low
    contractions: list[float] = []
    for i in range(len(swing_highs)):
        sh_idx, sh_price = swing_highs[i]
        # Find the next swing low after this swing high
        next_lows = [(si, sp) for si, sp in swing_lows if si > sh_idx]
        if not next_lows:
            continue
        sl_idx, sl_price = next_lows[0]
        if sh_price > 0:
            contraction_pct = (sh_price - sl_price) / sh_price * 100
            contractions.append(contraction_pct)

    if len(contractions) < 2:
        return default

    # Check if contractions are progressively tighter
    tightening_count = 0
    for i in range(1, len(contractions)):
        if contractions[i] < contractions[i - 1]:
            tightening_count += 1

    tightness = contractions[-1] / contractions[0] if contractions[0] > 0 else 1.0

    # ATR decline: compare ATR at base start vs current
    atr_series = ta.atr(
        pd.Series(r_high), pd.Series(r_low), pd.Series(r_close), length=14
    )
    if atr_series is not None and len(atr_series.dropna()) > 20:
        atr_clean = atr_series.dropna()
        atr_start = float(atr_clean.iloc[:10].mean())
        atr_end   = float(atr_clean.iloc[-10:].mean())
        atr_decline = (atr_start - atr_end) / atr_start * 100 if atr_start > 0 else 0.0
    else:
        atr_decline = 0.0

    # Volume decline: compare avg volume at base start vs current
    vol_start = float(np.mean(r_vol[:20])) if len(r_vol) >= 20 else float(np.mean(r_vol))
    vol_end   = float(np.mean(r_vol[-20:])) if len(r_vol) >= 20 else float(np.mean(r_vol))
    vol_decline = (vol_start - vol_end) / vol_start * 100 if vol_start > 0 else 0.0

    # VCP Score (0-100)
    # - Tightening contractions (0-30): reward progressively shallower pullbacks
    tighten_score = min(30.0, (tightening_count / max(1, len(contractions) - 1)) * 30.0)

    # - Tightness ratio (0-25): last contraction < 50% of first is ideal
    tight_ratio_score = _clamp((1.0 - tightness) * 50.0, 0.0, 25.0)

    # - ATR decline (0-25): 20%+ decline is strong
    atr_score = _clamp(atr_decline * 1.25, 0.0, 25.0)

    # - Volume dry-up (0-20): 30-50% decline is strong
    vol_score = _clamp(vol_decline * 0.5, 0.0, 20.0)

    vcp_score = tighten_score + tight_ratio_score + atr_score + vol_score

    # VCP detected if score > 40 and at least 2 tightening contractions
    vcp_detected = vcp_score >= 40.0 and tightening_count >= 1 and len(contractions) >= 2

    return {
        "vcp_detected":     bool(vcp_detected),
        "vcp_contractions": len(contractions),
        "vcp_tightness":    round(tightness, 3),
        "vcp_atr_decline":  round(atr_decline, 1),
        "vcp_vol_decline":  round(vol_decline, 1),
        "vcp_score":        round(vcp_score, 1),
    }


def _clamp(val: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, val))


# ── Keltner / Bollinger Squeeze ──────────────────────────────────────────────

def compute_squeeze(df: pd.DataFrame) -> dict[str, Any]:
    """
    Detect TTM Squeeze: Bollinger Bands contracting inside Keltner Channel.

    When BB is inside KC = "squeeze on" (extreme vol contraction, coiled spring).
    When BB expands back outside KC = "squeeze fire" (breakout imminent).

    Returns:
      - squeeze_on: True if BB is currently inside KC (coiling)
      - squeeze_fired: True if squeeze just released (last 5 bars)
      - squeeze_bars: how many consecutive bars the squeeze has been on
      - squeeze_score: 0-100 quality score (long squeeze → higher score)
    """
    default = {
        "squeeze_on": False, "squeeze_fired": False,
        "squeeze_bars": 0, "squeeze_score": 0.0,
    }

    close = df["Close"].squeeze()
    high  = df["High"].squeeze()
    low   = df["Low"].squeeze()

    if len(close) < 30:
        return default

    # Bollinger Bands (20, 2.0)
    bb = ta.bbands(close, length=20, std=2.0)
    if bb is None or bb.empty:
        return default

    bb_upper_col = [c for c in bb.columns if c.startswith("BBU_")]
    bb_lower_col = [c for c in bb.columns if c.startswith("BBL_")]
    if not bb_upper_col or not bb_lower_col:
        return default

    bb_upper = bb[bb_upper_col[0]]
    bb_lower = bb[bb_lower_col[0]]

    # Keltner Channel (20, 1.5x ATR)
    kc_mid = ta.ema(close, length=20)
    atr_series = ta.atr(high, low, close, length=20)
    if kc_mid is None or atr_series is None:
        return default

    kc_upper = kc_mid + 1.5 * atr_series
    kc_lower = kc_mid - 1.5 * atr_series

    # Squeeze: BB inside KC
    squeeze_series = (bb_lower > kc_lower) & (bb_upper < kc_upper)
    squeeze_vals = squeeze_series.dropna().tail(60)

    if len(squeeze_vals) < 5:
        return default

    squeeze_on = bool(squeeze_vals.iloc[-1])

    # Count consecutive squeeze bars
    squeeze_bars = 0
    for i in range(len(squeeze_vals) - 1, -1, -1):
        if squeeze_vals.iloc[i]:
            squeeze_bars += 1
        else:
            break

    # Squeeze fired: was on, now off (within last 5 bars)
    squeeze_fired = False
    if not squeeze_on and len(squeeze_vals) >= 6:
        # Check if squeeze was on recently and just released
        for i in range(2, min(6, len(squeeze_vals))):
            if squeeze_vals.iloc[-i]:
                squeeze_fired = True
                break

    # Squeeze score: longer squeezes build more energy
    if squeeze_on:
        # Currently squeezing — reward duration (6+ bars = building energy)
        squeeze_score = _clamp(squeeze_bars * 5.0, 0.0, 80.0)
    elif squeeze_fired:
        # Just fired — this is the actionable signal
        squeeze_score = 100.0
    else:
        squeeze_score = 0.0

    return {
        "squeeze_on":    squeeze_on,
        "squeeze_fired": squeeze_fired,
        "squeeze_bars":  squeeze_bars,
        "squeeze_score": round(squeeze_score, 1),
    }


# ── Master compute ─────────────────────────────────────────────────────────────

def compute_all(
    ticker: str,
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
) -> dict[str, Any] | None:
    """
    Compute all indicators for a single ticker.
    Returns a flat dict with all indicator values, or None if data insufficient.
    """
    if df is None or len(df) < config.MIN_DATA_ROWS:
        return None

    try:
        # Ensure column names are normalised
        df = df.copy()
        if hasattr(df.columns, "levels"):
            # Multi-level columns from batch download — flatten
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

        # Add EMAs
        df = compute_emas(df)

        close = float(df["Close"].iloc[-1])
        if close < config.MIN_PRICE:
            return None

        indicators: dict[str, Any] = {
            "ticker": ticker,
            "close":  round(close, 4),
        }

        # Price change %
        if len(df) >= 2:
            prev_close = float(df["Close"].iloc[-2])
            indicators["change_pct"] = round((close - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0.0
        else:
            indicators["change_pct"] = 0.0

        indicators.update(compute_ema_alignment(df))
        indicators.update(compute_52w_stats(df))
        indicators.update(compute_rsi(df))
        indicators.update(compute_macd(df))
        indicators.update(compute_adx(df))
        indicators.update(compute_obv(df))
        indicators.update(compute_cmf(df))
        indicators.update(compute_volume_analysis(df))
        indicators.update(compute_relative_strength(df, benchmark_df))
        indicators.update(compute_ibd_rs(df, benchmark_df))
        indicators.update(compute_vcp(df))
        indicators.update(compute_squeeze(df))

        return indicators

    except Exception as exc:
        logger.debug("Indicator compute failed for %s: %s", ticker, exc)
        return None
