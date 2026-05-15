"""
Score and rank all stocks in the universe (Russell 2000 + S&P 500).

v2 Pipeline:
1. Tier 1 — qualify.qualifies(ind) → hard gate (no graduated penalty)
2. Compute RS percentiles across qualifying universe (vs SPY benchmark)
3. Tier 2 — setup_score.compute_setup_score(ind) → 5 weighted categories
4. Tier 3 — penalties.compute_penalty_multiplier(ind) → multiplicative penalties
5. Composite = raw_setup_score * penalty_multiplier
6. Apply sector diversification cap
7. Return top N picks
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from . import config
from . import qualify, setup_score, penalties

logger = logging.getLogger(__name__)


# ── RS percentile computation ─────────────────────────────────────────────────

def compute_rs_percentiles(
    all_indicators: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    tickers     = [i["ticker"] for i in all_indicators]
    rs_3m_raw   = np.array([i.get("rs_raw_63d",  0.0) for i in all_indicators])
    rs_6m_raw   = np.array([i.get("rs_raw_126d", 0.0) for i in all_indicators])
    rs_12m_raw  = np.array([i.get("rs_raw_252d", 0.0) for i in all_indicators])
    ibd_rs_raw  = np.array([i.get("ibd_rs_raw",  0.0) for i in all_indicators])

    n = len(tickers)
    if n == 0:
        return {}

    def _percentile_ranks(values: np.ndarray) -> np.ndarray:
        ranks = np.zeros(n)
        for i, v in enumerate(values):
            ranks[i] = float(np.sum(values < v)) / (n - 1) * 100 if n > 1 else 50.0
        return ranks

    p3m  = _percentile_ranks(rs_3m_raw)
    p6m  = _percentile_ranks(rs_6m_raw)
    p12m = _percentile_ranks(rs_12m_raw)
    pibd = _percentile_ranks(ibd_rs_raw)

    return {
        tickers[i]: {
            "rs_3m_percentile":  round(float(p3m[i]),  1),
            "rs_6m_percentile":  round(float(p6m[i]),  1),
            "rs_12m_percentile": round(float(p12m[i]), 1),
            "ibd_rs_percentile": round(float(pibd[i]), 1),
        }
        for i in range(n)
    }


# ── v2 Orchestrator ───────────────────────────────────────────────────────────

def compute_composite(ind: dict[str, Any]) -> dict[str, Any]:
    """
    v2 composite scorer. Pipeline:
      1. qualify.qualifies(ind) → if fail, return qualifies=False, score=0
      2. setup_score.compute_setup_score(ind) → 5 categories + raw_setup_score
      3. penalties.compute_penalty_multiplier(ind) → multiplier + triggers
      4. composite = raw_setup_score * multiplier
    """
    ok, reason = qualify.qualifies(ind)
    if not ok:
        return {
            "qualifies":          False,
            "fail_reason":        reason,
            "composite_score":    0.0,
            "raw_setup_score":    0.0,
            "trend_strength":     0.0,
            "trend_cleanliness":  0.0,
            "rs":                 0.0,
            "base_setup":         0.0,
            "volume_profile":     0.0,
            "penalty_multiplier": 1.0,
            "penalty_triggered":  [],
        }
    scores = setup_score.compute_setup_score(ind)
    pen = penalties.compute_penalty_multiplier(ind)
    composite = scores["raw_setup_score"] * pen["final_multiplier"]
    return {
        "qualifies":          True,
        "fail_reason":        "",
        "composite_score":    round(composite, 1),
        "raw_setup_score":    scores["raw_setup_score"],
        "trend_strength":     scores["trend_strength"],
        "trend_cleanliness":  scores["trend_cleanliness"],
        "rs":                 scores["rs"],
        "base_setup":         scores["base_setup"],
        "volume_profile":     scores["volume_profile"],
        "penalty_multiplier": pen["final_multiplier"],
        "penalty_triggered":  pen["triggered"],
    }


# ── Sector info ───────────────────────────────────────────────────────────────

_SECTOR_CACHE_PATH = config.RESULTS_DIR / "sector_cache.json"


def _load_sector_cache() -> dict[str, dict[str, str]]:
    """Load cached sector info from disk."""
    import json
    if _SECTOR_CACHE_PATH.exists():
        try:
            with open(_SECTOR_CACHE_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_sector_cache(cache: dict[str, dict[str, str]]) -> None:
    """Persist sector cache to disk."""
    import json
    try:
        _SECTOR_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_SECTOR_CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as exc:
        logger.warning("Failed to save sector cache: %s", exc)


def fetch_sector_info(tickers: list[str]) -> dict[str, dict[str, str]]:
    """
    Fetch sector + company name for a small list of tickers.
    Uses a persistent disk cache since sector data rarely changes.
    Falls back to cache if yfinance API fails.
    """
    cache = _load_sector_cache()
    info: dict[str, dict[str, str]] = {}
    tickers_to_fetch = []

    # Use cache for tickers we already know
    for ticker in tickers:
        if ticker in cache and cache[ticker].get("sector", "Unknown") != "Unknown":
            info[ticker] = cache[ticker]
        else:
            tickers_to_fetch.append(ticker)

    # Fetch only unknown tickers from yfinance
    if tickers_to_fetch:
        import yfinance as yf
        logger.info("Fetching sector info for %d uncached tickers...", len(tickers_to_fetch))
        for ticker in tickers_to_fetch:
            try:
                t = yf.Ticker(ticker)
                data = t.info
                sector = data.get("sector") or "Unknown"
                entry = {
                    "company_name": data.get("longName") or data.get("shortName") or ticker,
                    "sector":       sector,
                    "industry":     data.get("industry") or "Unknown",
                }
                info[ticker] = entry
                if sector != "Unknown":
                    cache[ticker] = entry
            except Exception:
                # Fall back to cache even if it's "Unknown"
                info[ticker] = cache.get(ticker, {
                    "company_name": ticker,
                    "sector":       "Unknown",
                    "industry":     "Unknown",
                })

        _save_sector_cache(cache)
    else:
        logger.info("All %d tickers found in sector cache", len(tickers))

    return info


# ── Main ranking function ─────────────────────────────────────────────────────

def rank_stocks(
    all_indicators: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Full v2 pipeline: Tier 1 gate → RS percentiles → Tier 2 score → Tier 3 penalty
    → sector cap → top N.
    """
    screened_count = len(all_indicators)
    logger.info("Screening %d tickers...", screened_count)

    # 1. Tier 1 — qualification gate
    qualifying: list[dict[str, Any]] = []
    for ind in all_indicators:
        ok, _ = qualify.qualifies(ind)
        if ok:
            qualifying.append(ind)
    qualifying_count = len(qualifying)
    logger.info("Qualifying (passed Tier 1): %d", qualifying_count)
    if qualifying_count == 0:
        return [], {"screened_count": screened_count, "qualifying_count": 0}

    # 2. RS percentiles within qualifying universe
    percentiles = compute_rs_percentiles(qualifying)
    for ind in qualifying:
        ind.update(percentiles.get(ind["ticker"], {
            "rs_3m_percentile": 50.0, "rs_6m_percentile": 50.0,
            "rs_12m_percentile": 50.0, "ibd_rs_percentile": 50.0,
        }))

    # 3. Tier 2 + Tier 3 → composite
    for ind in qualifying:
        comp = compute_composite(ind)
        ind.update({
            "composite_score": comp["composite_score"],
            "raw_setup_score": comp["raw_setup_score"],
            "score_breakdown": {
                "trend_strength":     comp["trend_strength"],
                "trend_cleanliness":  comp["trend_cleanliness"],
                "rs":                 comp["rs"],
                "base_setup":         comp["base_setup"],
                "volume_profile":     comp["volume_profile"],
                "raw_setup_score":    comp["raw_setup_score"],
                "penalty_multiplier": comp["penalty_multiplier"],
                "penalty_triggered":  comp["penalty_triggered"],
                "composite_score":    comp["composite_score"],
            },
        })

    # 4. Sort by composite score (desc)
    qualifying.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)

    # 5. Sector diversification (preserve existing logic)
    candidate_tickers = [i["ticker"] for i in qualifying[:30]]
    logger.info("Fetching sector info for %d candidates...", len(candidate_tickers))
    sector_info = fetch_sector_info(candidate_tickers)
    known_sectors = sum(1 for v in sector_info.values() if v["sector"] != "Unknown")
    use_sector_cap = known_sectors >= len(sector_info) * 0.5
    if not use_sector_cap:
        logger.warning(
            "Sector lookup mostly failed (%d/%d unknown) — skipping sector cap",
            len(sector_info) - known_sectors, len(sector_info),
        )

    top_picks: list[dict[str, Any]] = []
    sector_counts: dict[str, int] = {}

    for ind in qualifying:
        if len(top_picks) >= config.TOP_N:
            break
        ticker = ind["ticker"]
        meta = sector_info.get(ticker, {"sector": "Unknown", "company_name": ticker, "industry": "Unknown"})
        sector = meta["sector"]
        if use_sector_cap and sector != "Unknown":
            if sector_counts.get(sector, 0) >= config.MAX_PICKS_PER_SECTOR:
                continue
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        ind.update(meta)
        top_picks.append(ind)

    logger.info("Top picks selected: %d", len(top_picks))

    return top_picks, {
        "screened_count":   screened_count,
        "qualifying_count": qualifying_count,
    }
