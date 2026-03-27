"""
Main orchestrator for the Russell 2000 Technical Screener.

Pipeline:
  1. Fetch tickers (IWM holdings or cache)
  2. Download OHLCV data (yfinance, 2-year lookback)
  3. Compute technical indicators for each ticker
  4. Score and rank (hard filters → composite score → top 20)
  5. Generate charts for top 15
  6. Write results/latest.json + results/history/DATE.json
  7. Send daily email (skipped with --dry-run)

Usage:
  python -m screener.main              # Full run (email sent)
  python -m screener.main --dry-run    # No email, results saved locally
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from multiprocessing import Pool, cpu_count
from typing import Any

from . import config
from .charts import generate_all_charts
from .data_fetcher import fetch_all_ohlcv, fetch_benchmark, get_russell2000_tickers
from .emailer import send_email
from .indicators import compute_all
from .scorer import rank_stocks

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("screener.main")


# ── Indicator computation (parallelised) ───────────────────────────────────────

def _compute_worker(args: tuple) -> dict[str, Any] | None:
    """Worker function for multiprocessing Pool."""
    ticker, df, benchmark_df = args
    return compute_all(ticker, df, benchmark_df)


def compute_all_indicators(
    all_ohlcv: dict,
    benchmark_df,
    workers: int | None = None,
) -> list[dict[str, Any]]:
    """Compute indicators for all tickers using a process pool."""
    tasks = [(t, df, benchmark_df) for t, df in all_ohlcv.items()]
    n_workers = workers or max(1, cpu_count() - 1)

    logger.info("Computing indicators for %d tickers (%d workers)...", len(tasks), n_workers)

    results: list[dict[str, Any]] = []
    # Use a pool only if there are many tickers (overhead not worth it for small sets)
    if len(tasks) > 50:
        with Pool(processes=n_workers) as pool:
            for result in pool.imap_unordered(_compute_worker, tasks, chunksize=10):
                if result is not None:
                    results.append(result)
    else:
        for task in tasks:
            result = _compute_worker(task)
            if result is not None:
                results.append(result)

    logger.info("Indicators computed for %d tickers", len(results))
    return results


# ── Results serialisation ──────────────────────────────────────────────────────

def _build_results_json(
    top_picks: list[dict[str, Any]],
    stats: dict[str, Any],
    run_date: str,
) -> dict[str, Any]:
    """Build the final results dict that gets written to latest.json."""
    picks_out = []
    for rank, pick in enumerate(top_picks, start=1):
        ticker = pick["ticker"]
        chart_fname = f"{ticker}_{run_date}.png"
        chart_url   = f"{config.GITHUB_RAW_BASE}/results/charts/{chart_fname}"

        picks_out.append({
            "rank":         rank,
            "ticker":       ticker,
            "company_name": pick.get("company_name", ticker),
            "sector":       pick.get("sector", "Unknown"),
            "industry":     pick.get("industry", "Unknown"),
            "close":        pick.get("close", 0.0),
            "change_pct":   pick.get("change_pct", 0.0),
            "volume":       pick.get("volume_today", 0),
            "avg_volume_20d": pick.get("avg_volume_20d", 0),
            "high_52w":     pick.get("high_52w", 0.0),
            "low_52w":      pick.get("low_52w", 0.0),
            "dist_from_52w_high_pct": pick.get("dist_from_52w_high_pct", 0.0),
            "composite_score": pick.get("composite_score", 0.0),
            "score_breakdown": {
                "trend_score":      pick.get("trend_score", 0.0),
                "rs_score":         pick.get("rs_score", 0.0),
                "volume_score":     pick.get("volume_score", 0.0),
                "momentum_score":   pick.get("momentum_score", 0.0),
                "pattern_score":    pick.get("pattern_score", 0.0),
                "extension_penalty": pick.get("extension_penalty", 1.0),
            },
            "indicators": {
                "ema_21":     pick.get("ema21", 0.0),
                "ema_50":     pick.get("ema50", 0.0),
                "ema_150":    pick.get("ema150", 0.0),
                "ema_200":    pick.get("ema200", 0.0),
                "ema_aligned": pick.get("ema_aligned", False),
                "ema_200_slope_pct": pick.get("ema200_slope", 0.0),
                "rsi_14":    pick.get("rsi_14", 0.0),
                "macd":      pick.get("macd", 0.0),
                "macd_signal": pick.get("macd_signal", 0.0),
                "macd_hist": pick.get("macd_hist", 0.0),
                "macd_crossover_bullish": pick.get("macd_crossover_bullish", False),
                "adx_14":    pick.get("adx_14", 0.0),
                "adx_trending": pick.get("adx_trending", False),
                "obv_trend": pick.get("obv_trend", "flat"),
                "cmf_20":    pick.get("cmf_20", 0.0),
                "rs_3m_percentile": pick.get("rs_3m_percentile", 0.0),
                "rs_6m_percentile": pick.get("rs_6m_percentile", 0.0),
                "ibd_rs_percentile": pick.get("ibd_rs_percentile", 0.0),
                "volume_ratio": pick.get("volume_ratio", 1.0),
                "vcp_detected":    pick.get("vcp_detected", False),
                "vcp_score":       pick.get("vcp_score", 0.0),
                "vcp_contractions": pick.get("vcp_contractions", 0),
                "vcp_tightness":   pick.get("vcp_tightness", 1.0),
                "squeeze_on":      pick.get("squeeze_on", False),
                "squeeze_fired":   pick.get("squeeze_fired", False),
                "squeeze_bars":    pick.get("squeeze_bars", 0),
                "squeeze_score":   pick.get("squeeze_score", 0.0),
                "extension_ema21_pct": pick.get("extension_ema21_pct", 0.0),
                "extension_ema50_pct": pick.get("extension_ema50_pct", 0.0),
                "atr_pct":             pick.get("atr_pct", 0.0),
                "extension_atr_multiple": pick.get("extension_atr_multiple", 0.0),
                "max_gap_pct":         pick.get("max_gap_pct", 0.0),
                "is_extended":         pick.get("is_extended", False),
            },
            "stage2":    pick.get("pattern_score", 0.0) >= 60.0,
            "vcp":       pick.get("vcp_detected", False),
            "squeeze":   pick.get("squeeze_fired", False) or pick.get("squeeze_on", False),
            "chart_url": chart_url,
        })

    return {
        "run_date":      run_date,
        "run_timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "screened_count":   stats.get("screened_count", 0),
        "qualifying_count": stats.get("qualifying_count", 0),
        "top_picks":        picks_out,
    }


def write_results(results: dict[str, Any], run_date: str) -> None:
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    config.HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    with open(config.LATEST_JSON, "w") as f:
        json.dump(results, f, indent=2)
    logger.info("Written: %s", config.LATEST_JSON)

    history_path = config.HISTORY_DIR / f"{run_date}.json"
    with open(history_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info("Written: %s", history_path)


# ── Main ───────────────────────────────────────────────────────────────────────

def main(dry_run: bool = False) -> int:
    run_date = datetime.now().strftime("%Y-%m-%d")
    logger.info("=== Russell 2000 Screener — %s ===", run_date)

    # 1. Get tickers
    tickers = get_russell2000_tickers()
    if not tickers:
        logger.error("No tickers loaded — aborting")
        return 1
    logger.info("Tickers to screen: %d", len(tickers))

    # 2. Fetch OHLCV data
    benchmark_df = fetch_benchmark()
    all_ohlcv    = fetch_all_ohlcv(tickers)
    if not all_ohlcv:
        logger.error("No OHLCV data returned — aborting")
        return 1

    # 3. Compute indicators
    all_indicators = compute_all_indicators(all_ohlcv, benchmark_df)
    if not all_indicators:
        logger.error("No indicators computed — aborting")
        return 1

    # 4. Score and rank
    top_picks, stats = rank_stocks(all_indicators)
    if not top_picks:
        logger.warning("No qualifying stocks found")
        stats["run_date"] = run_date

    # 5. Generate charts
    logger.info("Generating charts for top %d picks...", min(config.CHART_TOP_N, len(top_picks)))
    generate_all_charts(top_picks, all_ohlcv, benchmark_df, run_date)

    # 6. Write results JSON
    results = _build_results_json(top_picks, stats, run_date)
    write_results(results, run_date)

    # 7. Send email (skip on dry run; never crash the run)
    if dry_run:
        logger.info("Dry run — email skipped")
    else:
        try:
            send_email(top_picks, run_date, stats)
        except Exception:
            logger.exception("Email send failed (results still committed)")

    logger.info("=== Run complete: %d picks ===", len(top_picks))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Russell 2000 Technical Screener")
    parser.add_argument("--dry-run", action="store_true", help="Skip sending email")
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run))
