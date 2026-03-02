"""
Fetch Russell 2000 ticker list and OHLCV data via yfinance.

Ticker list sources (in order of priority):
1. iShares IWM ETF holdings CSV (always current)
2. Cached results/tickers.json in repo
"""
from __future__ import annotations

import json
import logging
import time
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import requests
import yfinance as yf

from . import config

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ── Ticker list ───────────────────────────────────────────────────────────────

def _fetch_iwm_holdings() -> list[str]:
    """Download iShares IWM holdings CSV and extract ticker symbols."""
    logger.info("Fetching IWM holdings from iShares...")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36"
        )
    }
    resp = requests.get(config.IWM_HOLDINGS_URL, headers=headers, timeout=30)
    resp.raise_for_status()

    # iShares CSV has header rows before the actual data; skip until 'Ticker' column
    lines = resp.text.splitlines()
    start_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("Ticker,") or ",Ticker," in line:
            start_idx = i
            break

    csv_body = "\n".join(lines[start_idx:])
    df = pd.read_csv(StringIO(csv_body))

    # Normalize column names
    df.columns = [c.strip() for c in df.columns]
    ticker_col = next(c for c in df.columns if c.lower() == "ticker")
    tickers = (
        df[ticker_col]
        .dropna()
        .astype(str)
        .str.strip()
        .str.replace(r"\s+", "", regex=True)
        .tolist()
    )
    # Filter out cash/other non-equity rows
    tickers = [t for t in tickers if t and t != "-" and t != "nan" and len(t) <= 5]
    logger.info("IWM holdings: %d tickers", len(tickers))
    return tickers


def _load_cached_tickers() -> list[str]:
    """Load ticker list from results/tickers.json fallback."""
    path = config.TICKERS_JSON
    if not path.exists():
        raise FileNotFoundError(f"No cached tickers at {path}")
    with open(path) as f:
        data = json.load(f)
    tickers = data if isinstance(data, list) else data.get("tickers", [])
    logger.info("Loaded %d cached tickers", len(tickers))
    return tickers


def get_russell2000_tickers() -> list[str]:
    """Return Russell 2000 tickers. Try live IWM holdings first, fallback to cache."""
    try:
        tickers = _fetch_iwm_holdings()
        # Cache for next time
        config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.TICKERS_JSON, "w") as f:
            json.dump(tickers, f)
        return tickers
    except Exception as exc:
        logger.warning("IWM holdings fetch failed (%s), using cached list", exc)
        return _load_cached_tickers()


# ── OHLCV download ────────────────────────────────────────────────────────────

def _download_batch(
    tickers: list[str], period: str, retries: int = 3
) -> dict[str, pd.DataFrame]:
    """Download OHLCV for a batch of tickers. Returns dict of valid DataFrames."""
    for attempt in range(retries):
        try:
            raw = yf.download(
                tickers,
                period=period,
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            break
        except Exception as exc:
            if attempt == retries - 1:
                logger.error("Batch download failed after %d retries: %s", retries, exc)
                return {}
            wait = 2 ** attempt
            logger.warning("Batch download error (attempt %d): %s. Retry in %ds", attempt + 1, exc, wait)
            time.sleep(wait)

    result: dict[str, pd.DataFrame] = {}

    # yfinance returns multi-level columns when multiple tickers
    if len(tickers) == 1:
        ticker = tickers[0]
        if not raw.empty and len(raw) >= config.MIN_DATA_ROWS:
            result[ticker] = raw.copy()
    else:
        for ticker in tickers:
            try:
                df = raw[ticker].copy()
                if df.empty or len(df) < config.MIN_DATA_ROWS:
                    continue
                if df["Close"].isna().all():
                    continue
                result[ticker] = df
            except (KeyError, TypeError):
                continue

    return result


def fetch_all_ohlcv(
    tickers: list[str],
    period: str = config.DATA_PERIOD,
    batch_size: int = config.BATCH_SIZE,
) -> dict[str, pd.DataFrame]:
    """
    Batch-download OHLCV for all tickers. Returns dict[ticker -> OHLCV DataFrame].
    DataFrames have columns: Open, High, Low, Close, Volume.
    """
    all_data: dict[str, pd.DataFrame] = {}
    total = len(tickers)

    for i in range(0, total, batch_size):
        batch = tickers[i : i + batch_size]
        logger.info(
            "Downloading batch %d/%d (tickers %d–%d of %d)...",
            i // batch_size + 1,
            (total + batch_size - 1) // batch_size,
            i + 1,
            min(i + batch_size, total),
            total,
        )
        batch_data = _download_batch(batch, period)
        all_data.update(batch_data)
        # Small pause between batches to be polite to Yahoo Finance
        if i + batch_size < total:
            time.sleep(0.5)

    logger.info(
        "Downloaded OHLCV for %d/%d tickers (%.1f%% success rate)",
        len(all_data),
        total,
        len(all_data) / total * 100 if total else 0,
    )
    return all_data


def fetch_benchmark(
    symbol: str = config.BENCHMARK_TICKER, period: str = config.DATA_PERIOD
) -> pd.DataFrame:
    """Download benchmark (IWM) OHLCV data."""
    logger.info("Fetching benchmark %s...", symbol)
    df = yf.download(symbol, period=period, auto_adjust=True, progress=False)
    if df.empty:
        raise RuntimeError(f"Failed to fetch benchmark {symbol}")
    logger.info("Benchmark %s: %d rows", symbol, len(df))
    return df
