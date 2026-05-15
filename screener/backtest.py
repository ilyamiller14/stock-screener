"""
v1-vs-v2 backtest harness.

For each date in the last N daily history files, compare:
  - v1 top-25 (from results/history/<date>.json) forward returns
  - v2 top-25 (re-scored from scratch with v2 logic) forward returns

Usage:
    python -m screener.backtest --days 30
Outputs:
    results/backtest_v2.csv
    summary printed to stdout
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from . import config, indicators, scorer

logger = logging.getLogger(__name__)


def _fwd_return(ticker: str, as_of: datetime, days: int) -> float | None:
    """Forward % return at +days sessions from as_of close."""
    start = as_of - timedelta(days=10)
    end = as_of + timedelta(days=days + 14)
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
        if df.empty:
            return None
        if hasattr(df.columns, "levels"):
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df.sort_index()
        on = df.loc[df.index <= as_of]
        if on.empty:
            return None
        as_of_close = float(on["Close"].iloc[-1])
        after = df.loc[df.index > as_of]
        if len(after) < days:
            return None
        fwd_close = float(after["Close"].iloc[days - 1])
        return (fwd_close / as_of_close - 1.0) * 100.0
    except Exception as exc:
        logger.debug("fwd_return failed for %s @ %s: %s", ticker, as_of.date(), exc)
        return None


def _v2_score_one(ticker: str, as_of: datetime, benchmark_df: pd.DataFrame) -> dict | None:
    """Re-fetch OHLCV up to as_of, compute v2 indicators + composite."""
    start = as_of - timedelta(days=730)
    try:
        df = yf.download(ticker, start=start, end=as_of + timedelta(days=1),
                         progress=False, auto_adjust=False)
        if df.empty or len(df) < config.MIN_DATA_ROWS:
            return None
        if hasattr(df.columns, "levels"):
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        ind = indicators.compute_all(ticker, df, benchmark_df)
        if ind is None:
            return None
        comp = scorer.compute_composite(ind)
        return {"ticker": ticker, **comp}
    except Exception as exc:
        logger.debug("_v2_score_one failed for %s @ %s: %s", ticker, as_of.date(), exc)
        return None


def backtest(days: int = 30) -> None:
    """Run v1-vs-v2 backtest over the last `days` daily history files."""
    hist_dir = Path(config.HISTORY_DIR)
    files = sorted(hist_dir.glob("*.json"))[-days:]
    out_rows: list[dict] = []

    bench_start = (datetime.utcnow() - timedelta(days=days + 800)).strftime("%Y-%m-%d")
    benchmark = yf.download(config.BENCHMARK_TICKER, start=bench_start,
                             auto_adjust=False, progress=False)
    if hasattr(benchmark.columns, "levels"):
        benchmark.columns = [c[0] if isinstance(c, tuple) else c for c in benchmark.columns]

    for f in files:
        try:
            as_of = datetime.strptime(f.stem, "%Y-%m-%d")
        except ValueError:
            continue
        with open(f) as fh:
            v1 = json.load(fh)
        v1_picks = v1.get("top_picks", [])
        v1_tickers = [p["ticker"] for p in v1_picks][:25]
        if not v1_tickers:
            continue

        v1_5d = [_fwd_return(t, as_of, 5) for t in v1_tickers]
        v1_20d = [_fwd_return(t, as_of, 20) for t in v1_tickers]
        v1_5d_clean = [r for r in v1_5d if r is not None]
        v1_20d_clean = [r for r in v1_20d if r is not None]
        v1_5d_avg = float(np.mean(v1_5d_clean)) if v1_5d_clean else None
        v1_20d_avg = float(np.mean(v1_20d_clean)) if v1_20d_clean else None

        bench_clip = benchmark.loc[benchmark.index <= as_of].copy()
        v2_scored = []
        for t in v1_tickers:
            row = _v2_score_one(t, as_of, bench_clip)
            if row and row.get("qualifies"):
                v2_scored.append(row)
        v2_scored.sort(key=lambda r: r["composite_score"], reverse=True)
        v2_tickers = [r["ticker"] for r in v2_scored][:25]
        v2_5d = [_fwd_return(t, as_of, 5) for t in v2_tickers]
        v2_20d = [_fwd_return(t, as_of, 20) for t in v2_tickers]
        v2_5d_clean = [r for r in v2_5d if r is not None]
        v2_20d_clean = [r for r in v2_20d if r is not None]
        v2_5d_avg = float(np.mean(v2_5d_clean)) if v2_5d_clean else None
        v2_20d_avg = float(np.mean(v2_20d_clean)) if v2_20d_clean else None

        rejected = len(v1_tickers) - len(v2_tickers)
        overlap = len(set(v1_tickers) & set(v2_tickers))

        row = {
            "date": as_of.strftime("%Y-%m-%d"),
            "v1_count": len(v1_tickers),
            "v2_count": len(v2_tickers),
            "overlap": overlap,
            "v1_rejected_by_v2_gate": rejected,
            "v1_avg_fwd_5d":  round(v1_5d_avg, 2)  if v1_5d_avg  is not None else None,
            "v2_avg_fwd_5d":  round(v2_5d_avg, 2)  if v2_5d_avg  is not None else None,
            "v1_avg_fwd_20d": round(v1_20d_avg, 2) if v1_20d_avg is not None else None,
            "v2_avg_fwd_20d": round(v2_20d_avg, 2) if v2_20d_avg is not None else None,
        }
        print(row)
        out_rows.append(row)

    out_path = Path(config.RESULTS_DIR) / "backtest_v2.csv"
    if out_rows:
        with open(out_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
            writer.writeheader()
            writer.writerows(out_rows)

        v1_5d_all  = [r["v1_avg_fwd_5d"]  for r in out_rows if r["v1_avg_fwd_5d"]  is not None]
        v2_5d_all  = [r["v2_avg_fwd_5d"]  for r in out_rows if r["v2_avg_fwd_5d"]  is not None]
        v1_20d_all = [r["v1_avg_fwd_20d"] for r in out_rows if r["v1_avg_fwd_20d"] is not None]
        v2_20d_all = [r["v2_avg_fwd_20d"] for r in out_rows if r["v2_avg_fwd_20d"] is not None]
        print(f"\n=== Summary across {len(out_rows)} dates ===")
        if v1_5d_all and v2_5d_all:
            print(f"v1 median fwd 5d:  {np.median(v1_5d_all):+.2f}%")
            print(f"v2 median fwd 5d:  {np.median(v2_5d_all):+.2f}%")
        if v1_20d_all and v2_20d_all:
            print(f"v1 median fwd 20d: {np.median(v1_20d_all):+.2f}%")
            print(f"v2 median fwd 20d: {np.median(v2_20d_all):+.2f}%")
        print(f"v1 picks rejected by v2 gate (avg/day): "
              f"{np.mean([r['v1_rejected_by_v2_gate'] for r in out_rows]):.1f}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    backtest(days=args.days)


if __name__ == "__main__":
    main()
