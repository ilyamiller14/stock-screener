"""
Generate publication-quality technical analysis charts.

Layout (1400x900, dark theme):
  Panel 1 (60%): Candlestick + EMA_21/50/150/200 + 52W high line + RS Line (right axis)
  Panel 2 (20%): Volume bars + 20d avg volume line + OBV (right axis)
  Panel 3 (20%): RSI with reference lines + MACD histogram + ADX (right axis)
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for CI/servers

import matplotlib.dates as mdates
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D

from . import config
from .indicators import compute_emas, compute_obv

logger = logging.getLogger(__name__)

# ── Color palette ─────────────────────────────────────────────────────────────
BG      = config.CHART_BG_COLOR
FG      = config.CHART_FG_COLOR
GREEN   = "#26a641"
RED     = "#da3633"
GOLD    = "#e3b341"
CYAN    = "#56d364"
PURPLE  = "#bc8cff"
GRID    = "#21262d"
AXIS_LBL = "#8b949e"
CANDLE_UP   = "#238636"
CANDLE_DOWN = "#da3633"


def _fmt_axis_value(x: float, _pos: object = None) -> str:
    """Format large numbers as K/M/B without scientific notation."""
    ax_val = abs(x)
    if ax_val >= 1e9:
        return f"{x/1e9:.1f}B"
    if ax_val >= 1e6:
        return f"{x/1e6:.1f}M"
    if ax_val >= 1e3:
        return f"{x/1e3:.0f}K"
    return f"{x:.0f}"


def _make_candlestick(ax: plt.Axes, df: pd.DataFrame) -> None:
    """Draw candlestick bars manually (mplfinance-style on a regular matplotlib axes)."""
    dates = mdates.date2num(df.index.to_pydatetime())
    width = 0.6

    for i, (date_num, row) in enumerate(zip(dates, df.itertuples())):
        open_, high, low, close = row.Open, row.High, row.Low, row.Close
        color = CANDLE_UP if close >= open_ else CANDLE_DOWN

        # Body
        body_bottom = min(open_, close)
        body_height = abs(close - open_)
        ax.bar(date_num, body_height, width=width * 0.8, bottom=body_bottom,
               color=color, edgecolor=color, linewidth=0.3, zorder=2)
        # Wick
        ax.plot([date_num, date_num], [low, high], color=color, linewidth=0.8, zorder=1)


def _add_ema_lines(ax: plt.Axes, df: pd.DataFrame) -> list[Line2D]:
    """Draw EMA lines. Returns list of Line2D for legend."""
    dates = mdates.date2num(df.index.to_pydatetime())
    lines = []
    labels = {21: "EMA 21", 50: "EMA 50", 150: "EMA 150", 200: "EMA 200"}
    widths = {21: 0.9, 50: 1.1, 150: 1.2, 200: 1.8}

    for period, color in config.EMA_COLORS.items():
        col = f"EMA_{period}"
        if col not in df.columns:
            continue
        vals = df[col].values
        mask = ~np.isnan(vals.astype(float))
        if mask.sum() < 2:
            continue
        line, = ax.plot(
            dates[mask], vals[mask],
            color=color,
            linewidth=widths[period],
            alpha=0.85,
            zorder=3,
            label=labels[period],
        )
        lines.append(line)
    return lines


def generate_chart(
    ticker: str,
    df_full: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    indicators: dict[str, Any],
    score_breakdown: dict[str, float],
    output_path: Path,
) -> None:
    """
    Generate and save a full technical analysis chart for a single ticker.

    df_full: 2-year daily OHLCV with EMA columns already added
    benchmark_df: IWM OHLCV for RS line computation
    indicators: flat indicator dict from indicators.py
    score_breakdown: composite + category scores from scorer.py
    output_path: where to save the PNG
    """
    # Trim to display window
    df = df_full.tail(config.CHART_BARS).copy()
    if len(df) < 30:
        logger.warning("Insufficient data for chart: %s (%d rows)", ticker, len(df))
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Compute OBV for display
    obv_data = compute_obv(df)
    close_s  = df["Close"].squeeze()
    volume_s = df["Volume"].squeeze()
    direction = np.sign(close_s.diff().fillna(0))
    obv_series = (direction * volume_s).cumsum()

    # RS Line: ticker price / IWM price (aligned dates)
    bench_tail = benchmark_df["Close"].squeeze().tail(config.CHART_BARS + 20)
    rs_line = close_s.div(bench_tail.reindex(close_s.index, method="ffill"))
    rs_line = rs_line.dropna()

    # RS RSI: momentum of relative strength (for Panel 4)
    import pandas_ta as _ta
    rs_rsi_series = _ta.rsi(rs_line, length=14) if len(rs_line) > 20 else None

    # 52W high line
    high_52w = indicators.get("high_52w", df["High"].max())

    # ── Figure layout ──────────────────────────────────────────────────────────
    fig = plt.figure(
        figsize=(
            config.CHART_WIDTH_PX / config.CHART_DPI,
            config.CHART_HEIGHT_PX / config.CHART_DPI,
        ),
        dpi=config.CHART_DPI,
        facecolor=BG,
    )
    gs = gridspec.GridSpec(
        4, 1,
        figure=fig,
        height_ratios=[0.50, 0.17, 0.17, 0.16],
        hspace=0.04,
    )

    ax1 = fig.add_subplot(gs[0])  # Price
    ax2 = fig.add_subplot(gs[1], sharex=ax1)  # Volume / OBV
    ax3 = fig.add_subplot(gs[2], sharex=ax1)  # RSI / MACD / ADX
    ax4 = fig.add_subplot(gs[3], sharex=ax1)  # RS RSI

    for ax in (ax1, ax2, ax3, ax4):
        ax.set_facecolor(BG)
        ax.tick_params(colors=AXIS_LBL, labelsize=7)
        ax.yaxis.label.set_color(AXIS_LBL)
        ax.xaxis.label.set_color(AXIS_LBL)
        for spine in ax.spines.values():
            spine.set_color(GRID)
        ax.grid(color=GRID, linewidth=0.4, linestyle="-", alpha=0.6)

    dates = mdates.date2num(df.index.to_pydatetime())

    # ── Panel 1: Price ─────────────────────────────────────────────────────────
    _make_candlestick(ax1, df)
    _add_ema_lines(ax1, df)

    # 52W high dashed line
    ax1.axhline(
        y=high_52w, color=FG, linewidth=0.7, linestyle="--", alpha=0.5,
        label=f"52W High {high_52w:.2f}",
    )

    # RS Line on right axis (purple)
    ax1_rs = ax1.twinx()
    ax1_rs.set_facecolor(BG)
    ax1_rs.tick_params(colors=PURPLE, labelsize=6)
    ax1_rs.yaxis.label.set_color(PURPLE)
    for spine in ax1_rs.spines.values():
        spine.set_color(GRID)

    if len(rs_line) > 1:
        rs_dates = mdates.date2num(rs_line.index.to_pydatetime())
        ax1_rs.plot(rs_dates, rs_line.values, color=PURPLE, linewidth=0.8, alpha=0.7, label="RS vs IWM")
        ax1_rs.set_ylabel("RS Line", color=PURPLE, fontsize=7)
    ax1_rs.yaxis.set_major_locator(mticker.MaxNLocator(nbins=4))

    # Legend
    ema_handles = [
        Line2D([0], [0], color=config.EMA_COLORS[p], linewidth=1.2, label=f"EMA {p}")
        for p in (21, 50, 150, 200)
        if f"EMA_{p}" in df.columns
    ]
    rs_handle = Line2D([0], [0], color=PURPLE, linewidth=1.0, label="RS vs IWM")
    ema_handles.append(rs_handle)
    ax1.legend(
        handles=ema_handles,
        loc="upper left",
        fontsize=6,
        facecolor="#161b22",
        edgecolor=GRID,
        labelcolor=FG,
        ncol=5,
    )

    # ── Panel 2: Volume + OBV ──────────────────────────────────────────────────
    up_mask   = df["Close"].values >= df["Open"].values
    down_mask = ~up_mask
    vol_vals  = df["Volume"].values

    ax2.bar(dates[up_mask],   vol_vals[up_mask],   width=0.6, color=CANDLE_UP,   alpha=0.7, zorder=2)
    ax2.bar(dates[down_mask], vol_vals[down_mask], width=0.6, color=CANDLE_DOWN, alpha=0.7, zorder=2)

    # 20d avg volume line
    avg_vol = indicators.get("avg_volume_20d", volume_s.tail(20).mean())
    ax2.axhline(y=avg_vol, color=GOLD, linewidth=0.7, linestyle="--", alpha=0.7, label="Avg Vol 20d")

    ax2.set_ylabel("Volume", color=AXIS_LBL, fontsize=7)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_axis_value))

    # OBV on right axis
    ax2_obv = ax2.twinx()
    ax2_obv.set_facecolor(BG)
    ax2_obv.tick_params(colors=CYAN, labelsize=6)
    for spine in ax2_obv.spines.values():
        spine.set_color(GRID)
    obv_dates = mdates.date2num(df.index.to_pydatetime())
    ax2_obv.plot(obv_dates, obv_series.values, color=CYAN, linewidth=0.8, alpha=0.8, label="OBV")
    ax2_obv.set_ylabel("OBV", color=CYAN, fontsize=6)
    ax2_obv.yaxis.set_major_formatter(mticker.FuncFormatter(_fmt_axis_value))
    ax2_obv.yaxis.set_major_locator(mticker.MaxNLocator(nbins=4))

    ax2.legend(loc="upper left", fontsize=5, facecolor="#161b22", edgecolor=GRID, labelcolor=FG)

    # ── Panel 3: RSI + MACD + ADX ─────────────────────────────────────────────
    from .indicators import compute_rsi as _rsi, compute_macd as _macd, compute_adx as _adx
    import pandas_ta as ta

    close_full = df["Close"].squeeze()

    rsi_series = ta.rsi(close_full, length=14)
    macd_df    = ta.macd(close_full, fast=12, slow=26, signal=9)
    adx_df     = ta.adx(df["High"].squeeze(), df["Low"].squeeze(), close_full, length=14)

    # RSI line
    if rsi_series is not None and not rsi_series.empty:
        rsi_dates = mdates.date2num(rsi_series.dropna().index.to_pydatetime())
        rsi_vals  = rsi_series.dropna().values
        ax3.plot(rsi_dates, rsi_vals, color="#2196F3", linewidth=0.9, label="RSI 14")
        ax3.axhline(y=70, color=RED,      linewidth=0.5, linestyle="--", alpha=0.6)
        ax3.axhline(y=50, color=AXIS_LBL, linewidth=0.5, linestyle="--", alpha=0.4)
        ax3.axhline(y=30, color=GREEN,    linewidth=0.5, linestyle="--", alpha=0.6)
        ax3.set_ylim(0, 100)
        ax3.set_yticks([30, 50, 70])
        ax3.tick_params(axis="y", colors="#2196F3", labelsize=6)

    # MACD histogram + signal on right axis
    ax3_macd = ax3.twinx()
    ax3_macd.set_facecolor(BG)
    for spine in ax3_macd.spines.values():
        spine.set_color(GRID)

    if macd_df is not None and not macd_df.empty:
        hist_col   = [c for c in macd_df.columns if c.startswith("MACDh_")]
        signal_col = [c for c in macd_df.columns if c.startswith("MACDs_")]
        macd_col   = [c for c in macd_df.columns if c.startswith("MACD_") and "h" not in c.lower() and "s" not in c.lower()]

        if hist_col:
            hist = macd_df[hist_col[0]].dropna()
            h_dates = mdates.date2num(hist.index.to_pydatetime())
            colors  = [GREEN if v >= 0 else RED for v in hist.values]
            ax3_macd.bar(h_dates, hist.values, width=0.6, color=colors, alpha=0.5, zorder=1)

        if macd_col and signal_col:
            m_series = macd_df[macd_col[0]].dropna()
            s_series = macd_df[signal_col[0]].dropna()
            shared_idx = m_series.index.intersection(s_series.index)
            ax3_macd.plot(
                mdates.date2num(shared_idx.to_pydatetime()),
                m_series.loc[shared_idx].values,
                color=FG, linewidth=0.7, alpha=0.8,
            )
            ax3_macd.plot(
                mdates.date2num(shared_idx.to_pydatetime()),
                s_series.loc[shared_idx].values,
                color=GOLD, linewidth=0.7, alpha=0.8,
            )

    ax3_macd.tick_params(colors=AXIS_LBL, labelsize=5)
    ax3_macd.yaxis.set_major_locator(mticker.MaxNLocator(nbins=4))
    ax3.set_ylabel("RSI", color="#2196F3", fontsize=7)
    ax3_macd.set_ylabel("MACD", color=AXIS_LBL, fontsize=6)

    # ── Panel 4: RS RSI ─────────────────────────────────────────────────────────
    RS_RSI_COLOR = "#E040FB"  # Bright magenta

    if rs_rsi_series is not None and not rs_rsi_series.empty:
        rs_rsi_clean = rs_rsi_series.dropna()
        if len(rs_rsi_clean) > 5:
            rs_rsi_dates = mdates.date2num(rs_rsi_clean.index.to_pydatetime())
            ax4.plot(rs_rsi_dates, rs_rsi_clean.values, color=RS_RSI_COLOR,
                     linewidth=0.9, label="RS RSI(14)")
            ax4.axhline(y=70, color=RED,      linewidth=0.5, linestyle="--", alpha=0.6)
            ax4.axhline(y=50, color=AXIS_LBL, linewidth=0.5, linestyle="--", alpha=0.4)
            ax4.axhline(y=30, color=GREEN,    linewidth=0.5, linestyle="--", alpha=0.6)
            ax4.set_ylim(0, 100)
            ax4.set_yticks([30, 50, 70])
            ax4.tick_params(axis="y", colors=RS_RSI_COLOR, labelsize=6)
            ax4.set_ylabel("RS RSI", color=RS_RSI_COLOR, fontsize=7)
            ax4.legend(loc="upper left", fontsize=5, facecolor="#161b22",
                       edgecolor=GRID, labelcolor=FG)

    # ── X-axis formatting ──────────────────────────────────────────────────────
    ax4.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax4.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.setp(ax4.xaxis.get_majorticklabels(), color=AXIS_LBL, fontsize=6, rotation=0)
    plt.setp(ax1.xaxis.get_majorticklabels(), visible=False)
    plt.setp(ax2.xaxis.get_majorticklabels(), visible=False)
    plt.setp(ax3.xaxis.get_majorticklabels(), visible=False)

    # ── Title ──────────────────────────────────────────────────────────────────
    company  = indicators.get("company_name", ticker)
    sector   = indicators.get("sector", "")
    score    = score_breakdown.get("composite_score", 0.0)
    rs_pct   = indicators.get("rs_3m_percentile", 0.0)
    adx_val  = indicators.get("adx_14", 0.0)
    cmf_val  = indicators.get("cmf_20", 0.0)
    obv_trend = indicators.get("obv_trend", "flat")
    run_date = datetime.now().strftime("%Y-%m-%d")

    title_text = f"${ticker}  |  {company}  |  {sector}  |  {run_date}"
    subtitle   = (
        f"Score: {score:.1f}  |  RS%: {rs_pct:.0f}  |  "
        f"ADX: {adx_val:.1f}  |  CMF: {cmf_val:+.2f}  |  OBV: {obv_trend.capitalize()}"
    )

    fig.text(
        0.01, 0.995, title_text,
        ha="left", va="top", color=FG, fontsize=9, fontweight="bold",
        transform=fig.transFigure,
    )
    fig.text(
        0.01, 0.977, subtitle,
        ha="left", va="top", color=AXIS_LBL, fontsize=7,
        transform=fig.transFigure,
    )

    fig.subplots_adjust(top=0.96, bottom=0.04, left=0.06, right=0.90)

    # ── Save ──────────────────────────────────────────────────────────────────
    fig.savefig(str(output_path), dpi=config.CHART_DPI, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    logger.info("Chart saved: %s", output_path)


def generate_all_charts(
    top_picks: list[dict[str, Any]],
    all_ohlcv: dict[str, pd.DataFrame],
    benchmark_df: pd.DataFrame,
    run_date: str,
) -> None:
    """Generate charts for top CHART_TOP_N picks."""
    config.CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    # Clean up old charts
    cutoff = datetime.now() - timedelta(days=config.CHART_CLEANUP_DAYS)
    for png in config.CHARTS_DIR.glob("*.png"):
        try:
            if datetime.fromtimestamp(png.stat().st_mtime) < cutoff:
                png.unlink()
                logger.debug("Deleted old chart: %s", png.name)
        except OSError:
            pass

    for pick in top_picks[:config.CHART_TOP_N]:
        ticker = pick["ticker"]
        df = all_ohlcv.get(ticker)
        if df is None:
            logger.warning("No OHLCV data for chart: %s", ticker)
            continue

        from .indicators import compute_emas
        df_with_ema = compute_emas(df.copy())

        output_path = config.CHARTS_DIR / f"{ticker}_{run_date}.png"
        try:
            generate_chart(
                ticker=ticker,
                df_full=df_with_ema,
                benchmark_df=benchmark_df,
                indicators=pick,
                score_breakdown=pick,
                output_path=output_path,
            )
        except Exception as exc:
            logger.error("Chart generation failed for %s: %s", ticker, exc)
