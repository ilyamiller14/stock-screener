"""
Central configuration: paths, thresholds, scoring weights.
All tunable parameters live here — do not scatter magic numbers.
"""
import os
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent.parent
RESULTS_DIR = ROOT_DIR / "results"
CHARTS_DIR = RESULTS_DIR / "charts"
HISTORY_DIR = RESULTS_DIR / "history"
LATEST_JSON = RESULTS_DIR / "latest.json"
TICKERS_JSON = RESULTS_DIR / "tickers.json"

# ── Data fetching ──────────────────────────────────────────────────────────────
# Primary: iShares IWM ETF holdings CSV (always current after annual reconstitution)
IWM_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239710/"
    "ishares-russell-2000-etf/1467271812596.ajax"
    "?fileType=csv&fileName=IWM_holdings&dataType=fund"
)
BENCHMARK_TICKER = "IWM"
DATA_PERIOD = "2y"       # 2 years for EMA_200 warmup (needs ~400 bars)
CHART_BARS = 150         # Display last 150 daily bars on charts
BATCH_SIZE = 100         # Tickers per yfinance batch call
MIN_DATA_ROWS = 200      # Minimum bars required for a ticker to be processed

# ── Hard filter gate (all must pass to enter scoring) ─────────────────────────
MIN_PRICE = 2.0                   # No penny stocks
MIN_AVG_VOLUME = 100_000          # 100k shares/day minimum liquidity
MIN_EMA200_SLOPE_SESSIONS = 20    # Rolling window for EMA_200 slope calc
EMA200_SLOPE_THRESHOLD = 0.0      # Slope must be > 0 (upward trend)

# ── Extension / gap-up filter ─────────────────────────────────────────────────
EXTENSION_ATR_MILD = 4.0          # 4x ATR above EMA21 → mild penalty starts
EXTENSION_ATR_HEAVY = 6.0         # 6x ATR → heavy penalty
EXTENSION_ATR_REJECT = 10.0       # 10x ATR → near-zero score
EXTENSION_EMA50_WARN_PCT = 20.0   # >20% above EMA50 → fallback penalty
GAP_LOOKBACK_DAYS = 20            # Scan last 20 days for large gaps
GAP_LARGE_PCT = 15.0              # Single-day gap >15% = suspect

# ── Selection output ───────────────────────────────────────────────────────────
TOP_N = 20                        # Total picks in output
CHART_TOP_N = 20                  # Charts generated for all top picks
MAX_PICKS_PER_SECTOR = 3          # Sector diversification cap

# ── Chart settings ─────────────────────────────────────────────────────────────
CHART_WIDTH_PX = 1400
CHART_HEIGHT_PX = 1050
CHART_DPI = 150
CHART_BG_COLOR = "#0D1117"
CHART_FG_COLOR = "#C9D1D9"
EMA_COLORS = {
    21:  "#00BCD4",   # Cyan
    50:  "#FFD700",   # Gold
    150: "#FF9800",   # Orange
    200: "#FFFFFF",   # White (boldest — Stage 2 anchor)
}
CHART_CLEANUP_DAYS = 7  # Delete PNGs older than this many days

# ── Scoring weights (must sum to 1.0) ─────────────────────────────────────────
CATEGORY_WEIGHTS = {
    "trend":    0.30,
    "rs":       0.25,
    "volume":   0.15,
    "momentum": 0.15,
    "pattern":  0.15,  # VCP + Squeeze + Stage 2
}

# Sub-weights within each category (must sum to 1.0)
TREND_SUB_WEIGHTS = {
    "ema_alignment":        0.30,
    "ema200_slope":         0.25,
    "dist_from_52w_high":   0.25,
    "adx":                  0.20,
}

RS_SUB_WEIGHTS = {
    "ibd_rs_percentile": 0.50,  # IBD-style quarter-weighted RS
    "rs_3m_percentile":  0.30,
    "rs_6m_percentile":  0.20,
}

VOLUME_SUB_WEIGHTS = {
    "obv_slope":          0.35,
    "cmf":                0.35,
    "upvol_ratio":        0.30,
}

MOMENTUM_SUB_WEIGHTS = {
    "rsi":             0.50,
    "macd_hist":       0.30,
    "macd_crossover":  0.20,
}

PATTERN_SUB_WEIGHTS = {
    "vcp":     0.40,  # VCP quality score
    "squeeze": 0.35,  # Keltner/BB squeeze
    "stage2":  0.25,  # Full Weinstein Stage 2
}

# RSI scoring: 60 is ideal (bullish momentum, not overbought)
RSI_IDEAL = 60.0
RSI_SCORE_DECAY = 3.33   # Points lost per unit of RSI deviation from ideal

# MACD crossover: score 100 if crossover within this many sessions, decays to 0 at double
MACD_CROSSOVER_MAX_SESSIONS = 10
MACD_CROSSOVER_DECAY_SESSIONS = 30

# ADX: score 100 at ADX ≥ 50
ADX_SCALE = 2.0          # adx * ADX_SCALE → raw score (capped at 100)

# Distance from 52W high: score 100 at the high, 0 at 25% below
DIST_52W_HIGH_SCALE = 4.0  # score = 100 - distance_pct * DIST_52W_HIGH_SCALE

# OBV slope normalization: slope as % of price, scaled up
OBV_SLOPE_SCALE = 1000.0

# ── Email settings ─────────────────────────────────────────────────────────────
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_RECIPIENTS = [
    r.strip()
    for r in os.environ.get("EMAIL_RECIPIENTS", "").split(",")
    if r.strip()
]

# GitHub raw CDN base for chart image URLs in emails
# Format: https://raw.githubusercontent.com/USER/REPO/main/results/charts/TICKER_DATE.png
GITHUB_RAW_BASE = os.environ.get(
    "GITHUB_RAW_BASE",
    "https://raw.githubusercontent.com/OWNER/stock-screener/main"
)
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://stock-screener-7gb.pages.dev")
