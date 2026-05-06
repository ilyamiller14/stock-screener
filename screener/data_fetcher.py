"""
Fetch ticker universe (Russell 2000 + S&P 500) and OHLCV data via yfinance.

Ticker list sources (in order of priority):
1. iShares IWM (Russell 2000) + IVV (S&P 500) holdings CSVs — always current
2. Cached results/tickers.json fallback
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

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
)


def _fetch_ishares_holdings(url: str, label: str) -> list[str]:
    """
    Generic iShares holdings CSV fetcher. Both IWM and IVV use the same CSV
    format with a header preamble before the 'Ticker,' column line.
    """
    logger.info("Fetching %s holdings from iShares...", label)
    resp = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=30)
    resp.raise_for_status()

    lines = resp.text.splitlines()
    start_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("Ticker,") or ",Ticker," in line:
            start_idx = i
            break

    csv_body = "\n".join(lines[start_idx:])
    df = pd.read_csv(StringIO(csv_body))

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
    # Filter out cash/non-equity rows (CASH_USD, "-", empty, etc.)
    tickers = [t for t in tickers if t and t != "-" and t != "nan" and len(t) <= 5]
    logger.info("%s holdings: %d tickers", label, len(tickers))
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


def get_universe_tickers() -> list[str]:
    """
    Return the combined Russell 2000 + S&P 500 ticker universe.
    Tries both iShares ETFs live, dedups, and caches the result. If both
    fetches fail, falls back to the cached tickers.json.
    """
    universe: list[str] = []
    fetched_any = False

    for url, label in [
        (config.IWM_HOLDINGS_URL, "IWM (Russell 2000)"),
        (config.IVV_HOLDINGS_URL, "IVV (S&P 500)"),
    ]:
        try:
            universe.extend(_fetch_ishares_holdings(url, label))
            fetched_any = True
        except Exception as exc:
            logger.warning("%s holdings fetch failed (%s)", label, exc)

    if not fetched_any:
        logger.warning("All live holdings fetches failed — using cached list")
        return _load_cached_tickers()

    # Dedup while preserving order. Some tickers may appear in both indexes
    # (e.g. promotions during the year between Russell rebalances).
    seen: set[str] = set()
    deduped: list[str] = []
    for t in universe:
        if t in seen:
            continue
        seen.add(t)
        deduped.append(t)

    logger.info(
        "Universe: %d unique tickers (R2000+S&P500, %d duplicates removed)",
        len(deduped),
        len(universe) - len(deduped),
    )

    # Cache the deduped union for future fallback runs.
    try:
        config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.TICKERS_JSON, "w") as f:
            json.dump(deduped, f)
    except Exception as exc:
        logger.warning("Failed to cache ticker list: %s", exc)

    return deduped


# Backwards-compat alias — old callers still get the new combined universe.
get_russell2000_tickers = get_universe_tickers


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
