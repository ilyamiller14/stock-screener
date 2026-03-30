"""
Macro / sector ETF analysis with support/resistance detection.

Generates standalone ETF charts (candlestick + S/R zones) and ratio charts
for market regime analysis. Only charts at "interesting" levels (testing S/R,
extreme RSI, breakout/breakdown) are included in the daily email.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import pandas_ta as ta
import yfinance as yf

from . import config

logger = logging.getLogger(__name__)

# ── Colors (match existing chart theme) ──────────────────────────────────────
BG       = config.CHART_BG_COLOR
FG       = config.CHART_FG_COLOR
GREEN    = "#26a641"
RED      = "#da3633"
GOLD     = "#e3b341"
GRID     = "#21262d"
AXIS_LBL = "#8b949e"
CANDLE_UP   = "#238636"
CANDLE_DOWN = "#da3633"
SR_SUPPORT_COLOR = "#26a641"
SR_RESIST_COLOR  = "#da3633"


# ── Data fetching ────────────────────────────────────────────────────────────

def fetch_macro_data(etf_tickers: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """Download OHLCV for all macro ETFs."""
    logger.info("Fetching macro ETF data for %d tickers...", len(etf_tickers))
    result: dict[str, pd.DataFrame] = {}

    for ticker in etf_tickers:
        try:
            df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
            if df is not None and not df.empty and len(df) >= 50:
                # Flatten multi-level columns if present
                if hasattr(df.columns, "levels"):
                    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                result[ticker] = df
            else:
                logger.warning("Insufficient data for macro ETF: %s", ticker)
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", ticker, exc)

    logger.info("Fetched macro data for %d/%d ETFs", len(result), len(etf_tickers))
    return result


def compute_ratio_series(
    etf_data: dict[str, pd.DataFrame],
    pairs: list[dict[str, str]],
) -> dict[str, pd.DataFrame]:
    """Compute ratio = num_close / den_close for each pair."""
    ratios: dict[str, pd.DataFrame] = {}

    for pair in pairs:
        num, den = pair["num"], pair["den"]
        name = f"{num}/{den}"
        if num not in etf_data or den not in etf_data:
            logger.warning("Missing data for ratio %s", name)
            continue

        num_close = etf_data[num]["Close"].squeeze()
        den_close = etf_data[den]["Close"].squeeze()
        # Align dates
        aligned = pd.DataFrame({"num": num_close, "den": den_close}).dropna()
        if len(aligned) < 50:
            continue

        ratio = aligned["num"] / aligned["den"]
        ratios[name] = pd.DataFrame({"Close": ratio}, index=aligned.index)

    return ratios


# ── Support / Resistance detection ───────────────────────────────────────────

def _find_swing_points(prices: np.ndarray, pivot: int = 5) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Find swing highs and lows using N-bar pivot detection."""
    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []

    for i in range(pivot, len(prices) - pivot):
        window = prices[i - pivot : i + pivot + 1]
        if prices[i] == np.max(window):
            swing_highs.append((i, float(prices[i])))
        if prices[i] == np.min(window):
            swing_lows.append((i, float(prices[i])))

    return swing_highs, swing_lows


def _cluster_pivots(
    pivot_prices: list[float],
    tolerance_pct: float,
    min_touches: int,
) -> list[tuple[float, int]]:
    """Group nearby pivot prices into S/R levels. Returns [(level_price, touch_count)]."""
    if not pivot_prices:
        return []

    sorted_pivots = sorted(pivot_prices)
    clusters: list[list[float]] = [[sorted_pivots[0]]]

    for price in sorted_pivots[1:]:
        cluster_mean = np.mean(clusters[-1])
        if abs(price - cluster_mean) / cluster_mean * 100 <= tolerance_pct:
            clusters[-1].append(price)
        else:
            clusters.append([price])

    return [
        (float(np.median(c)), len(c))
        for c in clusters
        if len(c) >= min_touches
    ]


def detect_support_resistance(
    prices: pd.Series,
    tolerance_pct: float = config.MACRO_SR_TOLERANCE_PCT,
    min_touches: int = config.MACRO_SR_MIN_TOUCHES,
) -> list[dict[str, Any]]:
    """Find S/R levels using pivot clustering."""
    arr = prices.values.astype(float)
    if len(arr) < 30:
        return []

    swing_highs, swing_lows = _find_swing_points(arr)

    # Combine all pivot prices for clustering
    all_pivots = [p for _, p in swing_highs] + [p for _, p in swing_lows]
    if not all_pivots:
        return []

    clustered = _cluster_pivots(all_pivots, tolerance_pct, min_touches)

    current_price = float(arr[-1])
    levels = []
    for level_price, touch_count in clustered:
        sr_type = "support" if level_price <= current_price else "resistance"
        levels.append({
            "price": round(level_price, 4),
            "touches": touch_count,
            "type": sr_type,
        })

    # Sort by touch count (strongest first)
    levels.sort(key=lambda x: x["touches"], reverse=True)
    return levels


# ── Interest scoring ─────────────────────────────────────────────────────────

def compute_interest_score(
    prices: pd.Series,
    sr_levels: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score 0-100 for how interesting this chart is right now."""
    current = float(prices.iloc[-1])
    score = 0
    components: dict[str, Any] = {}

    # ATR for distance normalization
    if len(prices) >= 15:
        highs = prices.rolling(1).max()
        lows = prices.rolling(1).min()
        tr = pd.concat([
            highs - lows,
            (prices - prices.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.tail(14).mean())
    else:
        atr = float(prices.std()) if len(prices) > 1 else 1.0

    if atr <= 0:
        atr = 1.0

    # 1. Proximity to nearest S/R level (0-30)
    nearest_level = None
    min_dist_atr = float("inf")
    for level in sr_levels:
        dist = abs(current - level["price"]) / atr
        if dist < min_dist_atr:
            min_dist_atr = dist
            nearest_level = level

    if min_dist_atr <= 1.0:
        prox_score = 30
    elif min_dist_atr <= 2.0:
        prox_score = 15
    elif min_dist_atr <= 3.0:
        prox_score = 5
    else:
        prox_score = 0
    score += prox_score
    components["proximity"] = {"score": prox_score, "nearest": nearest_level, "dist_atr": round(min_dist_atr, 1)}

    # 2. Touch count at nearest level (0-20)
    touches = nearest_level["touches"] if nearest_level else 0
    touch_score = min(20, touches * 7) if touches >= 2 else 0
    score += touch_score
    components["touches"] = {"score": touch_score, "count": touches}

    # 3. RSI extreme (0-20)
    rsi_series = ta.rsi(prices, length=14)
    rsi_val = float(rsi_series.iloc[-1]) if rsi_series is not None and not rsi_series.empty and not np.isnan(rsi_series.iloc[-1]) else 50.0
    if rsi_val < 30 or rsi_val > 70:
        rsi_score = 20
    elif rsi_val < 35 or rsi_val > 65:
        rsi_score = 10
    else:
        rsi_score = 0
    score += rsi_score
    components["rsi"] = {"score": rsi_score, "value": round(rsi_val, 1)}

    # 4. Breakout/breakdown in last 5 bars (0-20)
    breakout_score = 0
    if sr_levels and len(prices) >= 6:
        recent = prices.tail(6).values
        for level in sr_levels[:5]:
            lp = level["price"]
            # Price crossed through a level in last 5 bars
            above_before = recent[0] > lp
            above_now = recent[-1] > lp
            if above_before != above_now:
                breakout_score = 20
                break
    score += breakout_score
    components["breakout"] = {"score": breakout_score}

    # 5. MA interaction (0-10)
    ma_score = 0
    if len(prices) >= 50:
        ma50 = float(ta.ema(prices, length=50).iloc[-1])
        if not np.isnan(ma50) and abs(current - ma50) / current * 100 < 0.5:
            ma_score = 10
    if ma_score == 0 and len(prices) >= 200:
        ma200 = float(ta.ema(prices, length=200).iloc[-1])
        if not np.isnan(ma200) and abs(current - ma200) / current * 100 < 0.5:
            ma_score = 10
    score += ma_score
    components["ma_interaction"] = {"score": ma_score}

    # Generate narrative
    narrative = _build_narrative(current, nearest_level, rsi_val, breakout_score > 0)

    return {
        "interest_score": min(100, score),
        "components": components,
        "rsi": round(rsi_val, 1),
        "narrative": narrative,
    }


def _build_narrative(
    current: float,
    nearest_level: dict | None,
    rsi: float,
    is_breakout: bool,
) -> str:
    """Generate a human-readable description of what's happening."""
    if nearest_level is None:
        return "No key levels nearby"

    level_price = nearest_level["price"]
    touches = nearest_level["touches"]
    sr_type = nearest_level["type"]

    if is_breakout:
        action = f"Breaking {'above' if current > level_price else 'below'} {sr_type}"
    else:
        action = f"Testing {sr_type}"

    rsi_desc = ""
    if rsi < 30:
        rsi_desc = " | Oversold"
    elif rsi > 70:
        rsi_desc = " | Overbought"

    return f"{action} at {level_price:.2f} ({touches} touches){rsi_desc}"


# ── Chart generation ─────────────────────────────────────────────────────────

def _setup_axes(fig, gs_idx, gs):
    """Create and style an axes with dark theme."""
    ax = fig.add_subplot(gs[gs_idx])
    ax.set_facecolor(BG)
    ax.tick_params(colors=AXIS_LBL, labelsize=7)
    ax.yaxis.label.set_color(AXIS_LBL)
    ax.xaxis.label.set_color(AXIS_LBL)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.grid(color=GRID, linewidth=0.4, linestyle="-", alpha=0.6)
    return ax


def _draw_sr_zones(ax, sr_levels: list[dict], y_min: float, y_max: float):
    """Draw S/R levels as shaded horizontal bands with touch count labels."""
    y_range = y_max - y_min if y_max > y_min else 1.0
    band_half = y_range * 0.005  # 0.5% of chart range for band thickness

    for level in sr_levels:
        price = level["price"]
        touches = level["touches"]
        sr_type = level["type"]

        color = SR_SUPPORT_COLOR if sr_type == "support" else SR_RESIST_COLOR
        alpha = min(0.35, 0.10 + touches * 0.06)

        ax.axhspan(price - band_half, price + band_half,
                   color=color, alpha=alpha, zorder=1)
        ax.axhline(y=price, color=color, linewidth=0.6, linestyle="--",
                   alpha=0.5, zorder=1)

        # Touch count label on right margin
        ax.annotate(
            f"{touches}",
            xy=(1.01, price), xycoords=("axes fraction", "data"),
            fontsize=7, color=color, fontweight="bold",
            va="center", ha="left",
        )


def generate_macro_chart(
    ticker: str,
    df: pd.DataFrame,
    sr_levels: list[dict],
    interest: dict[str, Any],
    output_path: Path,
) -> None:
    """Generate standalone ETF chart with candlestick + S/R zones + RSI."""
    display = df.tail(config.MACRO_CHART_BARS).copy()
    if len(display) < 30:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    close_s = display["Close"].squeeze()

    fig = plt.figure(
        figsize=(
            config.MACRO_CHART_WIDTH_PX / config.CHART_DPI,
            config.MACRO_CHART_HEIGHT_PX / config.CHART_DPI,
        ),
        dpi=config.CHART_DPI,
        facecolor=BG,
    )
    gs = gridspec.GridSpec(2, 1, figure=fig, height_ratios=[0.70, 0.30], hspace=0.04)

    ax1 = _setup_axes(fig, 0, gs)
    ax2 = _setup_axes(fig, 1, gs)

    dates = mdates.date2num(display.index.to_pydatetime())

    # ── Panel 1: Candlestick + EMAs + S/R zones ──────────────────────────────
    width = 0.6
    for date_num, row in zip(dates, display.itertuples()):
        open_, high, low, close = row.Open, row.High, row.Low, row.Close
        color = CANDLE_UP if close >= open_ else CANDLE_DOWN
        body_bottom = min(open_, close)
        body_height = abs(close - open_)
        ax1.bar(date_num, body_height, width=width * 0.8, bottom=body_bottom,
                color=color, edgecolor=color, linewidth=0.3, zorder=2)
        ax1.plot([date_num, date_num], [low, high], color=color, linewidth=0.8, zorder=1)

    # 50d and 200d EMAs
    ema50 = ta.ema(close_s, length=50)
    ema200 = ta.ema(close_s, length=200)
    if ema50 is not None:
        mask = ~np.isnan(ema50.values.astype(float))
        ax1.plot(dates[mask], ema50.values[mask], color=GOLD, linewidth=1.0, alpha=0.8, label="EMA 50")
    if ema200 is not None:
        mask = ~np.isnan(ema200.values.astype(float))
        if mask.sum() > 1:
            ax1.plot(dates[mask], ema200.values[mask], color="#FFFFFF", linewidth=1.2, alpha=0.8, label="EMA 200")

    # S/R zones
    y_min, y_max = ax1.get_ylim()
    _draw_sr_zones(ax1, sr_levels, y_min, y_max)

    ax1.legend(loc="upper left", fontsize=6, facecolor="#161b22", edgecolor=GRID, labelcolor=FG)

    # ── Panel 2: RSI ─────────────────────────────────────────────────────────
    rsi_series = ta.rsi(close_s, length=14)
    if rsi_series is not None and not rsi_series.empty:
        rsi_clean = rsi_series.dropna()
        if len(rsi_clean) > 5:
            rsi_dates = mdates.date2num(rsi_clean.index.to_pydatetime())
            ax2.plot(rsi_dates, rsi_clean.values, color="#2196F3", linewidth=0.9, label="RSI 14")
            ax2.axhline(y=70, color=RED, linewidth=0.5, linestyle="--", alpha=0.6)
            ax2.axhline(y=50, color=AXIS_LBL, linewidth=0.5, linestyle="--", alpha=0.4)
            ax2.axhline(y=30, color=GREEN, linewidth=0.5, linestyle="--", alpha=0.6)
            ax2.set_ylim(0, 100)
            ax2.set_yticks([30, 50, 70])
            ax2.tick_params(axis="y", colors="#2196F3", labelsize=6)
            ax2.set_ylabel("RSI", color="#2196F3", fontsize=7)

    # ── X-axis formatting ────────────────────────────────────────────────────
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax2.xaxis.get_majorticklabels(), color=AXIS_LBL, fontsize=6, rotation=0)
    plt.setp(ax1.xaxis.get_majorticklabels(), visible=False)

    # ── Title ────────────────────────────────────────────────────────────────
    narrative = interest.get("narrative", "")
    title = f"${ticker}  |  {narrative}"
    fig.text(0.01, 0.99, title, ha="left", va="top", color=FG,
             fontsize=10, fontweight="bold", transform=fig.transFigure)

    fig.subplots_adjust(top=0.94, bottom=0.06, left=0.06, right=0.93)
    fig.savefig(str(output_path), dpi=config.CHART_DPI, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    logger.info("Macro chart saved: %s", output_path)


def generate_ratio_chart(
    pair_name: str,
    ratio_df: pd.DataFrame,
    sr_levels: list[dict],
    pair_info: dict[str, str],
    interest: dict[str, Any],
    output_path: Path,
) -> None:
    """Generate ratio chart with line + S/R zones + RSI."""
    display = ratio_df.tail(config.MACRO_CHART_BARS).copy()
    if len(display) < 30:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    close_s = display["Close"].squeeze()

    fig = plt.figure(
        figsize=(
            config.MACRO_CHART_WIDTH_PX / config.CHART_DPI,
            config.MACRO_CHART_HEIGHT_PX / config.CHART_DPI,
        ),
        dpi=config.CHART_DPI,
        facecolor=BG,
    )
    gs = gridspec.GridSpec(2, 1, figure=fig, height_ratios=[0.70, 0.30], hspace=0.04)

    ax1 = _setup_axes(fig, 0, gs)
    ax2 = _setup_axes(fig, 1, gs)

    dates = mdates.date2num(display.index.to_pydatetime())

    # ── Panel 1: Ratio line + EMAs + S/R zones ───────────────────────────────
    ax1.plot(dates, close_s.values, color=FG, linewidth=1.2, zorder=3, label=pair_name)

    ema50 = ta.ema(close_s, length=50)
    ema200 = ta.ema(close_s, length=200)
    if ema50 is not None:
        mask = ~np.isnan(ema50.values.astype(float))
        ax1.plot(dates[mask], ema50.values[mask], color=GOLD, linewidth=0.9, alpha=0.8, label="EMA 50")
    if ema200 is not None:
        mask = ~np.isnan(ema200.values.astype(float))
        if mask.sum() > 1:
            ax1.plot(dates[mask], ema200.values[mask], color="#FFFFFF", linewidth=1.0, alpha=0.8, label="EMA 200")

    y_min, y_max = ax1.get_ylim()
    _draw_sr_zones(ax1, sr_levels, y_min, y_max)

    ax1.legend(loc="upper left", fontsize=6, facecolor="#161b22", edgecolor=GRID, labelcolor=FG)

    # ── Panel 2: RSI of ratio ────────────────────────────────────────────────
    rsi_series = ta.rsi(close_s, length=14)
    if rsi_series is not None and not rsi_series.empty:
        rsi_clean = rsi_series.dropna()
        if len(rsi_clean) > 5:
            rsi_dates = mdates.date2num(rsi_clean.index.to_pydatetime())
            ax2.plot(rsi_dates, rsi_clean.values, color="#E040FB", linewidth=0.9, label="Ratio RSI(14)")
            ax2.axhline(y=70, color=RED, linewidth=0.5, linestyle="--", alpha=0.6)
            ax2.axhline(y=50, color=AXIS_LBL, linewidth=0.5, linestyle="--", alpha=0.4)
            ax2.axhline(y=30, color=GREEN, linewidth=0.5, linestyle="--", alpha=0.6)
            ax2.set_ylim(0, 100)
            ax2.set_yticks([30, 50, 70])
            ax2.tick_params(axis="y", colors="#E040FB", labelsize=6)
            ax2.set_ylabel("RSI", color="#E040FB", fontsize=7)

    # ── X-axis formatting ────────────────────────────────────────────────────
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax2.xaxis.get_majorticklabels(), color=AXIS_LBL, fontsize=6, rotation=0)
    plt.setp(ax1.xaxis.get_majorticklabels(), visible=False)

    # ── Title ────────────────────────────────────────────────────────────────
    narrative = interest.get("narrative", "")
    rising = pair_info.get("rising", "")
    falling = pair_info.get("falling", "")
    subtitle = f"Rising: {rising}  |  Falling: {falling}"
    title = f"{pair_name}  |  {pair_info.get('name', '')}  |  {narrative}"

    fig.text(0.01, 0.99, title, ha="left", va="top", color=FG,
             fontsize=10, fontweight="bold", transform=fig.transFigure)
    fig.text(0.01, 0.965, subtitle, ha="left", va="top", color=AXIS_LBL,
             fontsize=7, transform=fig.transFigure)

    fig.subplots_adjust(top=0.92, bottom=0.06, left=0.06, right=0.93)
    fig.savefig(str(output_path), dpi=config.CHART_DPI, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    logger.info("Ratio chart saved: %s", output_path)


# ── Orchestrator ─────────────────────────────────────────────────────────────

def run_macro_analysis(run_date: str) -> dict[str, Any]:
    """
    Full macro analysis pipeline:
    1. Fetch ETF data
    2. Detect S/R for each standalone ETF and each ratio
    3. Score interest
    4. Generate charts for interesting ones
    5. Return results dict
    """
    # 1. Fetch data
    etf_data = fetch_macro_data(config.MACRO_ETFS, period="1y")
    if not etf_data:
        logger.warning("No macro ETF data available")
        return {"etfs": [], "ratios": []}

    ratio_data = compute_ratio_series(etf_data, config.RATIO_PAIRS)

    charts_dir = config.CHARTS_DIR

    # 2-3. Analyse standalone ETFs
    etf_results: list[dict[str, Any]] = []
    for ticker, df in etf_data.items():
        close_s = df["Close"].squeeze()
        sr_levels = detect_support_resistance(close_s)
        interest = compute_interest_score(close_s, sr_levels)

        chart_fname = f"macro_{ticker}_{run_date}.png"
        chart_url = f"{config.GITHUB_RAW_BASE}/results/charts/{chart_fname}"

        entry = {
            "ticker": ticker,
            "interest_score": interest["interest_score"],
            "narrative": interest["narrative"],
            "sr_levels": sr_levels[:5],  # top 5 levels
            "rsi": interest["rsi"],
            "chart_url": chart_url,
        }

        # Generate chart if interesting enough
        if interest["interest_score"] >= config.MACRO_INTEREST_THRESHOLD:
            try:
                generate_macro_chart(
                    ticker, df, sr_levels, interest,
                    charts_dir / chart_fname,
                )
                entry["chart_generated"] = True
            except Exception as exc:
                logger.error("Macro chart failed for %s: %s", ticker, exc)
                entry["chart_generated"] = False
        else:
            entry["chart_generated"] = False

        etf_results.append(entry)

    # Sort by interest score, take top N
    etf_results.sort(key=lambda x: x["interest_score"], reverse=True)
    top_etfs = [e for e in etf_results if e["chart_generated"]][:config.MACRO_MAX_ETF_CHARTS]

    # 2-3. Analyse ratio pairs
    ratio_results: list[dict[str, Any]] = []
    for pair in config.RATIO_PAIRS:
        pair_name = f"{pair['num']}/{pair['den']}"
        if pair_name not in ratio_data:
            continue

        rdf = ratio_data[pair_name]
        close_s = rdf["Close"].squeeze()
        sr_levels = detect_support_resistance(close_s)
        interest = compute_interest_score(close_s, sr_levels)

        chart_fname = f"ratio_{pair['num']}_{pair['den']}_{run_date}.png"
        chart_url = f"{config.GITHUB_RAW_BASE}/results/charts/{chart_fname}"

        entry = {
            "pair": pair_name,
            "name": pair["name"],
            "rising": pair["rising"],
            "falling": pair["falling"],
            "interest_score": interest["interest_score"],
            "narrative": interest["narrative"],
            "sr_levels": sr_levels[:5],
            "rsi": interest["rsi"],
            "chart_url": chart_url,
        }

        if interest["interest_score"] >= config.MACRO_INTEREST_THRESHOLD:
            try:
                generate_ratio_chart(
                    pair_name, rdf, sr_levels, pair, interest,
                    charts_dir / chart_fname,
                )
                entry["chart_generated"] = True
            except Exception as exc:
                logger.error("Ratio chart failed for %s: %s", pair_name, exc)
                entry["chart_generated"] = False
        else:
            entry["chart_generated"] = False

        ratio_results.append(entry)

    ratio_results.sort(key=lambda x: x["interest_score"], reverse=True)
    top_ratios = [r for r in ratio_results if r["chart_generated"]][:config.MACRO_MAX_RATIO_CHARTS]

    total_charts = len(top_etfs) + len(top_ratios)
    logger.info(
        "Macro analysis complete: %d ETF charts + %d ratio charts (of %d ETFs, %d ratios analysed)",
        len(top_etfs), len(top_ratios), len(etf_results), len(ratio_results),
    )

    return {"etfs": top_etfs, "ratios": top_ratios}
