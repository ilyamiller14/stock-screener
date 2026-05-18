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
# Universe: Russell 2000 (small caps via IWM) + S&P 500 (large caps via IVV).
# Both pull from iShares holdings CSVs which are reconstituted continuously.
IWM_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239710/"
    "ishares-russell-2000-etf/1467271812596.ajax"
    "?fileType=csv&fileName=IWM_holdings&dataType=fund"
)
IVV_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239726/"
    "ishares-core-sp-500-etf/1467271812596.ajax"
    "?fileType=csv&fileName=IVV_holdings&dataType=fund"
)
UNIVERSE_LABEL = "Russell 2000 + S&P 500"
# Benchmark for relative-strength scoring. SPY is the natural choice for a
# mixed small/large universe — every ticker is graded against the same
# broad-market yardstick. (Was IWM when the universe was R2000-only.)
BENCHMARK_TICKER = "SPY"
DATA_PERIOD = "2y"       # 2 years for EMA_200 warmup (needs ~400 bars)
CHART_BARS = 150         # Display last 150 daily bars on charts
BATCH_SIZE = 100         # Tickers per yfinance batch call
MIN_DATA_ROWS = 200      # Minimum bars required for a ticker to be processed

# ── Hard filter gate (all must pass to enter scoring) ─────────────────────────
MIN_PRICE = 10.0                  # No penny stocks
MIN_AVG_VOLUME = 300_000          # 300k shares/day minimum liquidity
MIN_DOLLAR_VOLUME = 25_000_000    # $25M/day minimum — keeps thin micro-caps out
MIN_ADX = 20.0                    # ADX < 20 = no real trend; reject for Stage 2
MAX_DIST_FROM_52W_HIGH_PCT = 25.0 # Stage 2 picks must be within 25% of 52w high
MIN_EMA200_SLOPE_SESSIONS = 20    # Rolling window for EMA_200 slope calc
EMA200_SLOPE_THRESHOLD = 0.0      # Slope must be > 0 (upward trend)
MIN_PCT_ABOVE_52W_LOW = 30.0      # NEW — Minervini criterion 8
MIN_EMA200_RISING_SESSIONS = 22   # NEW — Minervini criterion 6 (1 trading month)

# ── Climactic / exhaustion hard rejects ───────────────────────────────────────
HARD_REJECT_1D_MOVE_PCT = 25.0    # Single-day close-to-close ≥ 25% → reject
HARD_REJECT_GAP_PCT = 20.0        # Overnight gap ≥ 20% → reject
HARD_REJECT_VOL_60D_PCT = 8.0     # 60d stdev of daily returns ≥ 8% → reject
EXTENSION_LOOKBACK_DAYS = 180     # Lookback window for hard-reject scans

# ── Extension / gap-up filter ─────────────────────────────────────────────────
EXTENSION_ATR_MILD = 4.0          # 4x ATR above EMA21 → mild penalty starts
EXTENSION_ATR_HEAVY = 6.0         # 6x ATR → heavy penalty
EXTENSION_ATR_REJECT = 10.0       # 10x ATR → near-zero score
EXTENSION_EMA50_WARN_PCT = 20.0   # >20% above EMA50 → fallback penalty
GAP_LOOKBACK_DAYS = 120           # Scan last 120 days for large gaps
GAP_LARGE_PCT = 15.0              # Single-day gap >15% = suspect
DIST_52W_LOW_MILD_PCT = 100.0     # v2.1: 60→100 — true leaders run 60-100% above 52w low, not over-extended
DIST_52W_LOW_HEAVY_PCT = 200.0    # v2.1: 120→200
DIST_52W_LOW_REJECT_PCT = 400.0   # v2.1: 250→400

# ── Climactic single-bar penalty bands ────────────────────────────────────────
CLIMACTIC_1D_MILD_PCT = 8.0       # v2.1: 10→8 — clustered 6-8% bars (CPRX) are climactic
CLIMACTIC_1D_HEAVY_PCT = 15.0
CLIMACTIC_1D_SEVERE_PCT = 20.0

# ── Exhaustion gap penalty bands (in addition to existing GAP_LARGE_PCT) ──────
GAP_PENALTY_MILD_PCT = 10.0
GAP_PENALTY_HEAVY_PCT = 15.0

# ── Rally concentration penalty bands (applied to MAX of 20/60/120-day windows) ──
CONCENTRATION_MILD_PCT = 35.0     # max(conc_20d, conc_60d, conc_120d) ≥ 35
CONCENTRATION_SEVERE_PCT = 60.0
# Legacy aliases (kept so any external readers don't crash):
CONCENTRATION_60D_MILD_PCT = CONCENTRATION_MILD_PCT
CONCENTRATION_60D_SEVERE_PCT = CONCENTRATION_SEVERE_PCT

# ── Wide-spread wide-range bar (intraday H-L vs prev_close) penalty bands ─────
WSWR_RANGE_MILD_PCT = 15.0        # NEW v2.1 — 15% intraday range = warning
WSWR_RANGE_HEAVY_PCT = 22.0       # 22%+ = textbook climactic (CPRX April 27 was 19.2%)

# ── Recent reversal penalty bands ─────────────────────────────────────────────
REVERSAL_5D_MILD_PCT = 5.0        # v2.1: 3→5 — 3% pullback is normal noise
REVERSAL_5D_HEAVY_PCT = 10.0      # v2.1: 7→10

# ── Selection output ───────────────────────────────────────────────────────────
# Universe roughly doubled when S&P 500 was added (~2400 tickers vs ~1900).
# Bumping TOP_N + per-sector cap to allow more breadth without losing focus.
TOP_N = 25                        # Total picks in output
CHART_TOP_N = 25                  # Charts generated for all top picks
MAX_PICKS_PER_SECTOR = 4          # Sector diversification cap

# ── Chart settings ─────────────────────────────────────────────────────────────
CHART_WIDTH_PX = 1400
CHART_HEIGHT_PX = 1200
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

# ── Macro / sector ETF tracking ───────────────────────────────────────────────
MACRO_ETFS = [
    "SMH", "XLY", "XLP", "XLK", "XLE", "XLF", "KRE",
    "IWM", "SPY", "QQQ", "HYG", "TLT", "GLD", "SPHB", "SPLV",
]

RATIO_PAIRS = [
    {"num": "IWM",  "den": "SPY",  "name": "Small Cap / Large Cap",
     "rising": "Small-cap leadership", "falling": "Large-cap dominance"},
    {"num": "XLY",  "den": "XLP",  "name": "Discretionary / Staples",
     "rising": "Risk appetite", "falling": "Defensive rotation"},
    {"num": "HYG",  "den": "TLT",  "name": "High Yield / Treasuries",
     "rising": "Credit confidence", "falling": "Flight to safety"},
    {"num": "SMH",  "den": "SPY",  "name": "Semis / S&P 500",
     "rising": "Tech leadership", "falling": "Tech weakness"},
    {"num": "SPHB", "den": "SPLV", "name": "High Beta / Low Vol",
     "rising": "Risk-on", "falling": "Risk-off"},
    {"num": "XLK",  "den": "XLP",  "name": "Tech / Staples",
     "rising": "Growth leadership", "falling": "Defensive mode"},
]

MACRO_CHART_BARS = 200            # ~10 months of daily data for S/R detection
MACRO_SR_TOLERANCE_PCT = 1.5      # % band to merge nearby pivots into one level
MACRO_SR_MIN_TOUCHES = 2          # minimum touches to display a S/R level
MACRO_INTEREST_THRESHOLD = 40     # minimum interest score (0-100) to include in email
MACRO_MAX_ETF_CHARTS = 5          # max standalone ETF charts in email
MACRO_MAX_RATIO_CHARTS = 3        # max ratio charts in email
MACRO_CHART_WIDTH_PX = 1400
MACRO_CHART_HEIGHT_PX = 600

# ── Scoring weights (must sum to 1.0) ─────────────────────────────────────────
CATEGORY_WEIGHTS = {
    "trend_strength":    0.25,
    "trend_cleanliness": 0.15,
    "rs":                0.25,
    "base_setup":        0.20,
    "volume_profile":    0.15,
}

TREND_STRENGTH_SUB_WEIGHTS = {
    "ema_alignment":          0.20,
    "ema200_slope_sustained": 0.30,
    "ema50_above_ema200":     0.20,
    "dist_from_52w_high":     0.10,
    "adx_robust":             0.20,
}

TREND_CLEANLINESS_SUB_WEIGHTS = {
    "r2_log_60d":        0.60,
    "outlier_bar_ratio": 0.40,
}

RS_SUB_WEIGHTS = {
    "ibd_rs_percentile": 0.65,
    "rs_3m_percentile":  0.20,
    "rs_6m_percentile":  0.10,
    "rs_12m_percentile": 0.05,
}
RS_LINE_NEW_HIGH_BONUS = 10.0

BASE_SETUP_SUB_WEIGHTS = {
    # v2.1 rebalance: pivot_proximity over-strict (returns ~0 for most Stage-2 advances
    # that aren't sitting AT a tight base right now). Weight reduced 0.30→0.10,
    # squeeze takes its place at 0.50. Total still sums to 1.0.
    "vcp_guarded":     0.40,
    "pivot_proximity": 0.10,
    "squeeze":         0.50,
}

VOLUME_PROFILE_SUB_WEIGHTS = {
    "obv_slope":           0.20,
    "cmf":                 0.25,
    "pullback_vol_dryup":  0.25,
    "breakout_day_volume": 0.30,
}

# Legacy aliases so any remaining import paths don't crash. Removed in a future cleanup.
TREND_SUB_WEIGHTS = TREND_STRENGTH_SUB_WEIGHTS
VOLUME_SUB_WEIGHTS = VOLUME_PROFILE_SUB_WEIGHTS

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

# ── Scorer version (embedded in latest.json for telling runs apart) ───────────
SCORER_VERSION = "2.0"
SCORER_REVISED_AT = "2026-05-15"

# ── VCP guard: reject if any bar moved more than this in 120-day lookback ─────
VCP_GUARD_MAX_BAR_PCT = 8.0       # v2.1: 12→8 — CWAN's 8% bar was reading as "clean" base
VCP_GUARD_MAX_GAP_PCT = 7.0       # v2.1: 10→7 — CWAN's 8.4% gap slipped under the old 10% bar
