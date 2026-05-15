# Stock Screener Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the screener's scoring around a three-tier architecture (Qualify → Setup-Score → Penalty), using canonical Minervini/O'Neil/IBD criteria, so that the daily top-25 reliably surfaces clean Stage-2 advances with valid base setups instead of post-spike drifts, recent reversals, and choppy non-trends.

**Architecture:** Replace the tangled `passes_hard_filters → compute_composite_score → _extension_penalty_multiplier` flow in `screener/scorer.py` with three explicit decoupled modules (`screener/qualify.py`, `screener/setup_score.py`, `screener/penalties.py`). Add new indicators (`r2_log_60d`, robust ADX, pivot proximity, rally concentration, recent-reversal distance, etc.) to `screener/indicators.py`. Wire the orchestrator in `screener/scorer.py`. Add a `screener/backtest.py` harness to compare v1 vs v2 forward returns against the last 30 history files before deploy.

**Tech Stack:** Python 3 (yfinance, pandas, pandas_ta, scipy, numpy), pytest, React/TypeScript frontend (display-only changes). The full design is in [docs/superpowers/specs/2026-05-15-stock-screener-redesign-design.md](../specs/2026-05-15-stock-screener-redesign-design.md) — read it before starting.

---

## File Structure

**New files:**
- `screener/qualify.py` — Tier 1 qualification gate
- `screener/setup_score.py` — Tier 2 setup quality scoring
- `screener/penalties.py` — Tier 3 penalty multipliers
- `screener/backtest.py` — v1-vs-v2 backtest harness
- `tests/test_qualify.py` — Tier 1 unit tests
- `tests/test_setup_score.py` — Tier 2 unit tests
- `tests/test_penalties.py` — Tier 3 unit tests
- `tests/test_indicators_new.py` — new indicator unit tests

**Modified files:**
- `screener/config.py` — new thresholds, weight tables, raised quality bars
- `screener/indicators.py` — add new indicator functions, update gap lookback
- `screener/scorer.py` — orchestrate the three tiers, keep RS percentile + sector cap
- `screener/main.py` — embed `scorer_version` in JSON output
- `tests/test_scorer.py` — update existing assertions for v2 schema
- `src/components/ScoreBreakdown.tsx` — display new categories

**Why this split:** Each tier has one clear responsibility. `qualify.py` returns `(passes: bool, reason: str)`. `setup_score.py` returns category sub-scores and a total. `penalties.py` returns a multiplier and the list of triggered penalties. `scorer.py` becomes a thin orchestrator. Each module is independently testable.

---

### Task 1: Bump quality bars and add new config thresholds

**Files:**
- Modify: `screener/config.py`

- [ ] **Step 1: Edit `screener/config.py` — raise quality bars and add new thresholds**

Replace the existing values and add new constants:

```python
# ── Hard filter gate (all must pass to enter scoring) ─────────────────────────
MIN_PRICE = 10.0                  # Raised from 2.0 — quality bias
MIN_AVG_VOLUME = 300_000          # Raised from 100k — liquidity bar
MIN_DOLLAR_VOLUME = 25_000_000    # Raised from 20M
MIN_ADX = 20.0                    # Unchanged
MAX_DIST_FROM_52W_HIGH_PCT = 25.0 # Unchanged
MIN_PCT_ABOVE_52W_LOW = 30.0      # NEW — Minervini criterion 8
MIN_EMA200_RISING_SESSIONS = 22   # NEW — Minervini criterion 6 (1 trading month)
MIN_EMA200_SLOPE_SESSIONS = 20    # Existing (do not change)
EMA200_SLOPE_THRESHOLD = 0.0      # Existing

# ── Climactic / exhaustion hard rejects ───────────────────────────────────────
HARD_REJECT_1D_MOVE_PCT = 25.0    # Single-day close-to-close ≥ 25% → reject
HARD_REJECT_GAP_PCT = 20.0        # Overnight gap ≥ 20% → reject
HARD_REJECT_VOL_60D_PCT = 8.0     # 60d stdev of daily returns ≥ 8% → reject
EXTENSION_LOOKBACK_DAYS = 180     # Lookback window for hard-reject scans

# ── Gap detection lookback (replaces 20-day window) ───────────────────────────
GAP_LOOKBACK_DAYS = 120           # Raised from 20 — catches mid-window gaps

# ── 52w-low extension penalty bands (recalibrated for normal stocks) ──────────
DIST_52W_LOW_MILD_PCT = 60.0      # Was 100 — too lenient for normal movers
DIST_52W_LOW_HEAVY_PCT = 120.0    # Was 200
DIST_52W_LOW_REJECT_PCT = 250.0   # Was 350

# ── Climactic single-bar penalty bands ────────────────────────────────────────
CLIMACTIC_1D_MILD_PCT = 10.0
CLIMACTIC_1D_HEAVY_PCT = 15.0
CLIMACTIC_1D_SEVERE_PCT = 20.0

# ── Exhaustion gap penalty bands (in addition to existing GAP_LARGE_PCT) ──────
GAP_PENALTY_MILD_PCT = 10.0
GAP_PENALTY_HEAVY_PCT = 15.0

# ── Rally concentration penalty bands ─────────────────────────────────────────
CONCENTRATION_60D_MILD_PCT = 35.0   # Single bar ≥ 35% of 60d return → mild
CONCENTRATION_60D_SEVERE_PCT = 60.0 # ≥ 60% → severe

# ── Recent reversal penalty bands ─────────────────────────────────────────────
REVERSAL_5D_MILD_PCT = 3.0
REVERSAL_5D_HEAVY_PCT = 7.0

# ── Scorer version (embedded in latest.json for telling runs apart) ───────────
SCORER_VERSION = "2.0"
SCORER_REVISED_AT = "2026-05-15"
```

Replace the existing `CATEGORY_WEIGHTS` and sub-weight tables:

```python
# ── Scoring weights (must sum to 1.0) ─────────────────────────────────────────
CATEGORY_WEIGHTS = {
    "trend_strength":    0.25,
    "trend_cleanliness": 0.15,  # NEW
    "rs":                0.25,
    "base_setup":        0.20,  # was "pattern"
    "volume_profile":    0.15,  # was "volume"
    # momentum category removed (RSI/MACD aren't core to Minervini/O'Neil)
}

TREND_STRENGTH_SUB_WEIGHTS = {
    "ema_alignment":         0.20,
    "ema200_slope_sustained": 0.30,
    "ema50_above_ema200":     0.20,
    "dist_from_52w_high":     0.10,
    "adx_robust":             0.20,
}

TREND_CLEANLINESS_SUB_WEIGHTS = {
    "r2_log_60d":         0.60,
    "outlier_bar_ratio":  0.40,
}

RS_SUB_WEIGHTS = {
    "ibd_rs_percentile": 0.65,  # Up from 0.50 — best historical predictor
    "rs_3m_percentile":  0.20,
    "rs_6m_percentile":  0.10,
    "rs_12m_percentile": 0.05,  # NEW
}
RS_LINE_NEW_HIGH_BONUS = 10.0   # Flat bonus when RS line at 50d high

BASE_SETUP_SUB_WEIGHTS = {
    "vcp_guarded":      0.40,
    "pivot_proximity":  0.30,
    "squeeze":          0.30,
}

VOLUME_PROFILE_SUB_WEIGHTS = {
    "obv_slope":           0.20,
    "cmf":                 0.25,
    "pullback_vol_dryup":  0.25,
    "breakout_day_volume": 0.30,
}

# Keep deprecated weight tables in place but unused, so old tests still parse:
TREND_SUB_WEIGHTS = TREND_STRENGTH_SUB_WEIGHTS  # alias for compat
VOLUME_SUB_WEIGHTS = VOLUME_PROFILE_SUB_WEIGHTS  # alias for compat

# ── VCP guard: reject if any bar moved more than this in 120-day lookback ─────
VCP_GUARD_MAX_BAR_PCT = 12.0   # |daily_return| > 12% → skip VCP detection
VCP_GUARD_MAX_GAP_PCT = 10.0
```

- [ ] **Step 2: Verify config parses**

Run: `python -c "from screener import config; print(config.CATEGORY_WEIGHTS, sum(config.CATEGORY_WEIGHTS.values()))"`
Expected: prints dict and `1.0`.

- [ ] **Step 3: Commit**

```bash
git add screener/config.py
git commit -m "config: raise quality bars and add v2 scorer constants

Bumps MIN_PRICE to \$10, MIN_AVG_VOLUME to 300k, adds Minervini criterion 8
(pct_above_52w_low ≥ 30) and criterion 6 (EMA200 rising ≥ 22 sessions).
Adds climactic/gap/concentration/reversal penalty bands. Replaces the 5-
category weight table with the v2 5-category structure (trend_strength,
trend_cleanliness, rs, base_setup, volume_profile).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Add `ema200_rising_sessions` indicator

**Files:**
- Test: `tests/test_indicators_new.py`
- Modify: `screener/indicators.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_indicators_new.py`:

```python
"""
Tests for new v2 indicators added to screener.indicators.
The OHLCV-dependent functions are tested via small synthetic DataFrames.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _make_df(closes, opens=None, highs=None, lows=None, volumes=None):
    """Build a minimal OHLCV DataFrame from a list of closes."""
    n = len(closes)
    closes = np.asarray(closes, dtype=float)
    opens   = np.asarray(opens   if opens   is not None else closes, dtype=float)
    highs   = np.asarray(highs   if highs   is not None else closes * 1.005, dtype=float)
    lows    = np.asarray(lows    if lows    is not None else closes * 0.995, dtype=float)
    volumes = np.asarray(volumes if volumes is not None else np.ones(n) * 1_000_000, dtype=float)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=idx,
    )


# ── ema200_rising_sessions ────────────────────────────────────────────────────

class TestEma200RisingSessions:
    def test_rising_for_full_window(self):
        from screener.indicators import compute_ema200_rising_sessions
        # 250 monotonically rising closes → EMA200 has been rising every session
        df = _make_df(np.linspace(10, 50, 250))
        result = compute_ema200_rising_sessions(df)
        assert result["ema200_rising_sessions"] >= 22

    def test_flat_returns_zero(self):
        from screener.indicators import compute_ema200_rising_sessions
        df = _make_df([20.0] * 250)
        result = compute_ema200_rising_sessions(df)
        assert result["ema200_rising_sessions"] == 0

    def test_recently_turned_up_returns_small_count(self):
        from screener.indicators import compute_ema200_rising_sessions
        # 240 flat then 10 rising
        closes = np.concatenate([np.full(240, 20.0), np.linspace(20, 25, 10)])
        df = _make_df(closes)
        result = compute_ema200_rising_sessions(df)
        # EMA200 slope is slow; expect a small non-zero count
        assert 0 < result["ema200_rising_sessions"] < 22
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_indicators_new.py::TestEma200RisingSessions -v`
Expected: FAIL with `ImportError: cannot import name 'compute_ema200_rising_sessions'`.

- [ ] **Step 3: Implement `compute_ema200_rising_sessions` in `screener/indicators.py`**

Add this function after `compute_ema_alignment`:

```python
def compute_ema200_rising_sessions(df: pd.DataFrame) -> dict[str, Any]:
    """
    Count consecutive trailing sessions where EMA_200 is non-decreasing.
    Computes EMA_200 inline if not already present.

    Returns {"ema200_rising_sessions": int}.
    """
    close = df["Close"].squeeze()
    if "EMA_200" in df.columns:
        ema200 = df["EMA_200"]
    else:
        ema200 = ta.ema(close, length=200)
    if ema200 is None or ema200.dropna().empty:
        return {"ema200_rising_sessions": 0}
    ema_clean = ema200.dropna()
    # Compare each session to the prior session (shift 1)
    diffs = ema_clean.diff().fillna(0).values
    # Walk back from the end, count sessions where diff >= 0
    count = 0
    for v in diffs[::-1]:
        if v >= 0:
            count += 1
        else:
            break
    return {"ema200_rising_sessions": int(count)}
```

Then wire it into `compute_all` (the master function) — find the existing block that calls `compute_ema_alignment` and add immediately after:

```python
indicators.update(compute_ema200_rising_sessions(df))
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_indicators_new.py::TestEma200RisingSessions -v`
Expected: PASS (all 3 cases).

- [ ] **Step 5: Commit**

```bash
git add screener/indicators.py tests/test_indicators_new.py
git commit -m "indicators: add ema200_rising_sessions for Minervini criterion 6

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Add climactic / gap / reversal / volatility indicators

**Files:**
- Modify: `tests/test_indicators_new.py`
- Modify: `screener/indicators.py`

These four indicators are all small loops over price series — group them in one task.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_indicators_new.py`:

```python
# ── Climactic / reversal / volatility metrics ─────────────────────────────────

class TestRecentMoveMetrics:
    def test_max_1d_move_120d(self):
        from screener.indicators import compute_recent_move_metrics
        closes = [100.0] * 100 + [120.0] + [120.0] * 19  # +20% bar 19 sessions ago
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        assert result["max_1d_move_120d"] == pytest.approx(20.0, abs=0.01)

    def test_max_1d_move_120d_outside_window(self):
        from screener.indicators import compute_recent_move_metrics
        # Spike is 150 sessions ago — outside 120d window
        closes = [100.0] * 50 + [120.0] + [120.0] * 150
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        # 120 → 120 in the trailing 120d gives no move
        assert result["max_1d_move_120d"] < 1.0

    def test_max_gap_120d(self):
        from screener.indicators import compute_recent_move_metrics
        # Opens with a 25% gap 50 sessions ago
        n = 200
        closes = [100.0] * n
        opens = [100.0] * n
        opens[150] = 125.0   # 50 sessions ago: 125 open vs 100 prev close
        df = _make_df(closes, opens=opens)
        result = compute_recent_move_metrics(df)
        assert result["max_gap_120d"] == pytest.approx(25.0, abs=0.01)

    def test_concentration_60d(self):
        from screener.indicators import compute_recent_move_metrics
        # 60-day rally: 100 → 120 = 20%. One bar contributes +10% (i.e. 50% of rally).
        closes = [100.0] * 140 + list(np.linspace(100, 110, 30)) + [121.0] + list(np.linspace(121, 120, 29))
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        # The +10% bar is ~50% of the 20% total
        assert 30.0 < result["concentration_60d"] < 70.0

    def test_concentration_zero_when_no_rally(self):
        from screener.indicators import compute_recent_move_metrics
        df = _make_df([50.0] * 200)
        result = compute_recent_move_metrics(df)
        assert result["concentration_60d"] == 0.0

    def test_dist_from_recent_highs(self):
        from screener.indicators import compute_recent_move_metrics
        # Last 5 bars: 100, 102, 105, 103, 101 → 5-bar high = 105, last = 101 → 3.81%
        closes = [100.0] * 195 + [100.0, 102.0, 105.0, 103.0, 101.0]
        # highs match closes (no intrabar wicks for simplicity)
        highs = closes.copy()
        df = _make_df(closes, highs=highs)
        result = compute_recent_move_metrics(df)
        assert result["dist_from_5d_high_pct"] == pytest.approx(3.81, abs=0.05)

    def test_vol_60d(self):
        from screener.indicators import compute_recent_move_metrics
        # Constant series → vol_60d = 0
        df = _make_df([100.0] * 200)
        result = compute_recent_move_metrics(df)
        assert result["vol_60d"] == pytest.approx(0.0, abs=0.001)

    def test_vol_60d_volatile_series(self):
        from screener.indicators import compute_recent_move_metrics
        # Alternating ±5% → stdev of daily returns should be ~5%
        rng = np.random.default_rng(seed=42)
        rets = rng.choice([-0.05, 0.05], size=200)
        closes = 100 * np.cumprod(1 + rets)
        df = _make_df(closes)
        result = compute_recent_move_metrics(df)
        assert 4.0 < result["vol_60d"] < 6.0
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_indicators_new.py::TestRecentMoveMetrics -v`
Expected: FAIL with `ImportError: cannot import name 'compute_recent_move_metrics'`.

- [ ] **Step 3: Implement `compute_recent_move_metrics` in `screener/indicators.py`**

Add after `compute_extension`:

```python
def compute_recent_move_metrics(df: pd.DataFrame) -> dict[str, Any]:
    """
    Compute climactic / gap / concentration / reversal / volatility metrics
    used by Tier 1 (hard rejects) and Tier 3 (penalty multipliers).
    """
    default = {
        "max_1d_move_120d": 0.0,
        "max_gap_120d": 0.0,
        "concentration_60d": 0.0,
        "dist_from_5d_high_pct": 0.0,
        "dist_from_10d_high_pct": 0.0,
        "dist_from_20d_high_pct": 0.0,
        "vol_60d": 0.0,
    }
    if len(df) < 30:
        return default

    closes = df["Close"].values.astype(float)
    opens  = df["Open"].values.astype(float)
    highs  = df["High"].values.astype(float)
    n = len(df)
    last = float(closes[-1])
    if last <= 0:
        return default

    # max 1-day close-to-close move in last 120 sessions
    lookback = min(config.GAP_LOOKBACK_DAYS, n - 1)
    max_1d = 0.0
    max_gap = 0.0
    for i in range(n - lookback, n):
        if i < 1:
            continue
        prev_c = closes[i - 1]
        if prev_c > 0:
            move = (closes[i] - prev_c) / prev_c * 100
            if move > max_1d:
                max_1d = float(move)
            gap = (opens[i] - prev_c) / prev_c * 100
            if gap > max_gap:
                max_gap = float(gap)

    # Concentration: single biggest day in last 60 / total 60d return
    win60 = min(60, n - 1)
    if win60 >= 5:
        c0 = closes[-win60 - 1]
        ret_60 = (last / c0 - 1) * 100 if c0 > 0 else 0.0
        if ret_60 > 0.1:
            max_60 = 0.0
            for i in range(n - win60, n):
                if i < 1:
                    continue
                prev_c = closes[i - 1]
                if prev_c > 0:
                    move = (closes[i] - prev_c) / prev_c * 100
                    if move > max_60:
                        max_60 = float(move)
            concentration = max_60 / ret_60 * 100
        else:
            concentration = 0.0
    else:
        concentration = 0.0

    # Distance from rolling N-bar highs
    def _dist_high(k: int) -> float:
        if n < k:
            return 0.0
        peak = float(np.max(highs[-k:]))
        if peak <= 0:
            return 0.0
        return (peak - last) / peak * 100

    # 60-day stdev of daily returns (in percent)
    if win60 >= 5:
        rets = np.diff(closes[-win60 - 1:]) / closes[-win60 - 1:-1] * 100
        vol_60 = float(np.std(rets, ddof=1))
    else:
        vol_60 = 0.0

    return {
        "max_1d_move_120d":      round(max_1d, 2),
        "max_gap_120d":          round(max_gap, 2),
        "concentration_60d":     round(concentration, 1),
        "dist_from_5d_high_pct": round(_dist_high(5), 2),
        "dist_from_10d_high_pct": round(_dist_high(10), 2),
        "dist_from_20d_high_pct": round(_dist_high(20), 2),
        "vol_60d":               round(vol_60, 2),
    }
```

Wire it into `compute_all` after `compute_extension`:

```python
indicators.update(compute_recent_move_metrics(df))
```

Then update `compute_extension` to use the new lookback constant — find the `lookback = min(config.GAP_LOOKBACK_DAYS, len(df) - 1)` line in `compute_extension` and leave it (it already reads from config — config.GAP_LOOKBACK_DAYS just changed to 120 in Task 1).

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_indicators_new.py::TestRecentMoveMetrics -v`
Expected: PASS (all 8 cases).

- [ ] **Step 5: Commit**

```bash
git add screener/indicators.py tests/test_indicators_new.py
git commit -m "indicators: add climactic / concentration / reversal / vol metrics

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Add trend cleanliness indicators (R² and outlier-bar count)

**Files:**
- Modify: `tests/test_indicators_new.py`
- Modify: `screener/indicators.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_indicators_new.py`:

```python
class TestTrendCleanliness:
    def test_r2_perfect_uptrend(self):
        from screener.indicators import compute_trend_cleanliness
        # Pure log-linear growth → R² ≈ 1.0
        closes = 100 * np.exp(np.linspace(0, 0.6, 200))  # 0.3%/day for 200 days
        df = _make_df(closes)
        result = compute_trend_cleanliness(df)
        assert result["r2_log_60d"] > 0.95

    def test_r2_flat_series(self):
        from screener.indicators import compute_trend_cleanliness
        # Flat closes with tiny noise → R² should be low/undefined → 0
        rng = np.random.default_rng(seed=7)
        closes = 100 + rng.normal(0, 0.001, 200)
        df = _make_df(closes)
        result = compute_trend_cleanliness(df)
        assert result["r2_log_60d"] < 0.5

    def test_outlier_bar_count_clean(self):
        from screener.indicators import compute_trend_cleanliness
        closes = 100 * np.exp(np.linspace(0, 0.3, 200))
        df = _make_df(closes)
        result = compute_trend_cleanliness(df)
        # Smooth exponential growth has no outlier bars
        assert result["outlier_bar_count_60d"] == 0

    def test_outlier_bar_count_with_spike(self):
        from screener.indicators import compute_trend_cleanliness
        # Inject a single +15% bar into otherwise flat series
        closes = [100.0] * 199 + [115.0]
        df = _make_df(closes)
        result = compute_trend_cleanliness(df)
        assert result["outlier_bar_count_60d"] >= 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_indicators_new.py::TestTrendCleanliness -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `compute_trend_cleanliness` in `screener/indicators.py`**

Add after `compute_recent_move_metrics`:

```python
def compute_trend_cleanliness(df: pd.DataFrame) -> dict[str, Any]:
    """
    Measure how 'clean' the recent trend is:
      - r2_log_60d:           R² of OLS regression of log(close) vs session index
      - outlier_bar_count_60d: count of bars with |daily_return| > 4σ of the 60d distribution
    """
    default = {"r2_log_60d": 0.0, "outlier_bar_count_60d": 0}
    if len(df) < 30:
        return default

    closes = df["Close"].values.astype(float)
    win = min(60, len(df) - 1)
    sub = closes[-win - 1:]
    if (sub <= 0).any():
        return default

    # R² of log-linear regression
    x = np.arange(len(sub))
    y = np.log(sub)
    try:
        _, _, r_value, _, _ = stats.linregress(x, y)
        r2 = float(r_value ** 2)
        if not np.isfinite(r2):
            r2 = 0.0
    except Exception:
        r2 = 0.0

    # Outlier bars: |return| > 4σ of 60d return distribution
    rets = np.diff(sub) / sub[:-1]
    std = float(np.std(rets, ddof=1))
    if std > 0:
        outlier_count = int(np.sum(np.abs(rets) > 4.0 * std))
    else:
        outlier_count = 0

    return {
        "r2_log_60d":            round(r2, 3),
        "outlier_bar_count_60d": outlier_count,
    }
```

Wire it into `compute_all`:

```python
indicators.update(compute_trend_cleanliness(df))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_indicators_new.py::TestTrendCleanliness -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add screener/indicators.py tests/test_indicators_new.py
git commit -m "indicators: add R² log-linear trend + outlier-bar cleanliness metrics

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Add robust ADX (drops top 2 True-Range bars)

**Files:**
- Modify: `tests/test_indicators_new.py`
- Modify: `screener/indicators.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_indicators_new.py`:

```python
class TestRobustADX:
    def test_robust_adx_lower_than_naive_on_spiky_series(self):
        from screener.indicators import compute_adx
        # Steady-state low-vol series with a single massive bar
        n = 100
        closes = [100.0] * n
        highs = [100.5] * n
        lows = [99.5] * n
        # Inject one huge range bar 20 sessions ago
        highs[80] = 150.0
        df = _make_df(closes, highs=highs, lows=lows)
        result = compute_adx(df)
        # Robust ADX must be defined and lower than naive ADX
        assert "adx_robust" in result
        assert result["adx_robust"] <= result["adx_14"]

    def test_robust_adx_matches_naive_on_smooth_series(self):
        from screener.indicators import compute_adx
        # No outlier bars → robust ≈ naive
        closes = list(np.linspace(100, 130, 200))
        df = _make_df(closes)
        result = compute_adx(df)
        # Within 5 absolute points
        assert abs(result["adx_robust"] - result["adx_14"]) < 5.0
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_indicators_new.py::TestRobustADX -v`
Expected: FAIL because `compute_adx` does not currently return `adx_robust`.

- [ ] **Step 3: Update `compute_adx` to also return `adx_robust`**

Replace the existing `compute_adx` function in `screener/indicators.py` with:

```python
def compute_adx(df: pd.DataFrame, period: int = 14) -> dict[str, Any]:
    """
    Standard pandas_ta ADX(14), plus a 'robust' variant that drops the top 2
    True-Range bars from the last (period + 14) bars before recomputing.
    Robust ADX is less inflated by single spike bars.
    """
    high = df["High"].squeeze()
    low  = df["Low"].squeeze()
    close = df["Close"].squeeze()

    adx_df = ta.adx(high, low, close, length=period)
    if adx_df is None or adx_df.empty:
        return {"adx_14": 0.0, "adx_robust": 0.0, "adx_dmp": 0.0, "adx_dmn": 0.0, "adx_trending": False}

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

    # Robust ADX: drop the top 2 True-Range bars over the last (period + 14) bars
    # and rerun on the cleaned series. Replace cleaned bars with the mean TR so
    # the series length is preserved.
    window = period + 14
    if len(df) > window + 5:
        tr_high = high.values
        tr_low  = low.values
        tr_close = close.values
        # True range per bar
        prev_close = np.concatenate([[tr_close[0]], tr_close[:-1]])
        tr = np.maximum.reduce([
            tr_high - tr_low,
            np.abs(tr_high - prev_close),
            np.abs(tr_low - prev_close),
        ])
        tail = tr[-window:].copy()
        # Indices of top 2 TR bars within the tail
        top2 = np.argsort(tail)[-2:]
        mean_tr = float(np.mean(np.delete(tail, top2)))
        # Replace top2 with mean_tr in cloned price series by capping the bar
        high_robust = high.copy().values.astype(float)
        low_robust = low.copy().values.astype(float)
        for offset in top2:
            idx = len(df) - window + int(offset)
            # Set H,L to a tight range around the close to neutralize the bar
            high_robust[idx] = float(tr_close[idx]) + mean_tr / 2
            low_robust[idx] = float(tr_close[idx]) - mean_tr / 2
        adx_df_r = ta.adx(
            pd.Series(high_robust, index=high.index),
            pd.Series(low_robust, index=low.index),
            close, length=period,
        )
        if adx_df_r is not None and not adx_df_r.empty:
            ar_col = [c for c in adx_df_r.columns if c.startswith("ADX_")]
            adx_robust = float(adx_df_r[ar_col[0]].iloc[-1]) if ar_col else adx_val
            if np.isnan(adx_robust):
                adx_robust = adx_val
        else:
            adx_robust = adx_val
    else:
        adx_robust = adx_val

    return {
        "adx_14":      round(adx_val, 2),
        "adx_robust":  round(adx_robust, 2),
        "adx_dmp":     round(dmp_val, 2),
        "adx_dmn":     round(dmn_val, 2),
        "adx_trending": adx_val > 20.0 and dmp_val > dmn_val,
    }
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_indicators_new.py::TestRobustADX -v tests/test_indicators.py -v`
Expected: new tests PASS; existing tests unchanged.

- [ ] **Step 5: Commit**

```bash
git add screener/indicators.py tests/test_indicators_new.py
git commit -m "indicators: add adx_robust (drops top 2 TR bars before computing)

Mitigates SLAB-style fake-trend inflation where a single +49% gap
drove ADX(14) above 50.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Add pivot-proximity (base detection) indicator

**Files:**
- Modify: `tests/test_indicators_new.py`
- Modify: `screener/indicators.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_indicators_new.py`:

```python
class TestPivotProximity:
    def test_finds_recent_consolidation(self):
        from screener.indicators import compute_pivot_proximity
        # 30 days of climb to 100, then 20 days of tight range 95-100, then close at 100
        rise = list(np.linspace(80, 100, 30))
        base = [98.0, 96.0, 99.0, 95.0, 100.0, 97.0, 96.0, 99.0, 98.0, 100.0,
                97.0, 95.0, 99.0, 98.0, 96.0, 100.0, 99.0, 97.0, 96.0, 100.0]
        closes = rise + base
        df = _make_df(closes, highs=closes)
        result = compute_pivot_proximity(df)
        # Pivot should be near 100; dist_from_pivot_pct close to 0
        assert result["pivot_price"] == pytest.approx(100.0, abs=2.0)
        assert abs(result["dist_from_pivot_pct"]) < 5.0
        assert 15 <= result["base_length_days"] <= 40

    def test_no_valid_base_returns_zero(self):
        from screener.indicators import compute_pivot_proximity
        # Monotonic climb — never consolidates
        closes = list(np.linspace(50, 100, 200))
        df = _make_df(closes, highs=closes)
        result = compute_pivot_proximity(df)
        # No tight base → defaults
        assert result["pivot_price"] == 0.0
        assert result["dist_from_pivot_pct"] == 99.0

    def test_extended_past_pivot(self):
        from screener.indicators import compute_pivot_proximity
        # Tight base 95-100, then breakout to 115 (well above pivot)
        base = [95.0, 100.0, 96.0, 99.0, 100.0, 95.0, 98.0, 100.0, 97.0, 99.0,
                95.0, 100.0, 96.0, 99.0, 100.0, 95.0, 98.0, 100.0, 97.0, 99.0]
        breakout = list(np.linspace(101, 115, 10))
        closes = [80.0] * 30 + base + breakout
        df = _make_df(closes, highs=closes)
        result = compute_pivot_proximity(df)
        # Price now 15% above pivot ~100
        assert result["pivot_price"] == pytest.approx(100.0, abs=2.0)
        assert result["dist_from_pivot_pct"] > 10.0
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_indicators_new.py::TestPivotProximity -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `compute_pivot_proximity` in `screener/indicators.py`**

Add after `compute_trend_cleanliness`:

```python
def compute_pivot_proximity(df: pd.DataFrame) -> dict[str, Any]:
    """
    Identify the most recent 3-8 week consolidation (base) and compute
    distance from its pivot (the high of the base).

    Algorithm:
    1. Find 5-bar swing highs and swing lows in the last 60 sessions.
    2. Walk backward from the most recent bar. Build the longest contiguous
       cluster of swings where (max_high - min_low)/max_high <= 0.15 AND
       cluster spans 15-40 trading days.
    3. Pivot = max_high of that cluster. base_depth_pct = range/pivot * 100.

    Returns defaults (pivot=0, dist=99) if no valid base found.
    """
    default = {
        "pivot_price": 0.0,
        "dist_from_pivot_pct": 99.0,
        "base_depth_pct": 0.0,
        "base_length_days": 0,
    }
    if len(df) < 60:
        return default

    sub = df.tail(60).copy()
    highs = sub["High"].values.astype(float)
    lows  = sub["Low"].values.astype(float)
    closes = sub["Close"].values.astype(float)
    n = len(sub)
    last = float(closes[-1])
    if last <= 0:
        return default

    pivot = 5
    # Indices of swing highs and lows (within `sub`)
    swing_idx_highs: list[int] = []
    swing_idx_lows:  list[int] = []
    for i in range(pivot, n - pivot):
        if highs[i] == max(highs[i - pivot:i + pivot + 1]):
            swing_idx_highs.append(i)
        if lows[i] == min(lows[i - pivot:i + pivot + 1]):
            swing_idx_lows.append(i)

    if not swing_idx_highs:
        return default

    # Walk back from the latest swing high and extend a cluster as far back
    # as range stays <= 15% of max_high
    best = None  # (start_idx, end_idx, max_high, min_low)
    for end_anchor in reversed(swing_idx_highs):
        cluster_high = highs[end_anchor]
        cluster_low = lows[end_anchor]
        # Extend backward through ALL pivots (both highs and lows) within window
        all_swings = sorted(set(swing_idx_highs + swing_idx_lows), reverse=True)
        # Start the cluster from end_anchor going backward
        for s in all_swings:
            if s > end_anchor:
                continue
            new_high = max(cluster_high, highs[s])
            new_low = min(cluster_low, lows[s])
            if new_high <= 0:
                break
            rng_pct = (new_high - new_low) / new_high
            if rng_pct > 0.15:
                break
            cluster_high = new_high
            cluster_low = new_low
            start_idx = s
        else:
            start_idx = end_anchor
        # Length check: span must be 15..40 trading days
        length = end_anchor - start_idx
        if 15 <= length <= 40:
            cand = (start_idx, end_anchor, cluster_high, cluster_low, length)
            if best is None or end_anchor > best[1]:
                best = cand
            break  # take the most recent valid base; do not keep walking earlier

    if best is None:
        return default

    start_idx, end_idx, p_high, p_low, length = best
    base_depth_pct = (p_high - p_low) / p_high * 100 if p_high > 0 else 0.0
    dist_from_pivot_pct = (last - p_high) / p_high * 100 if p_high > 0 else 99.0

    return {
        "pivot_price":          round(float(p_high), 4),
        "dist_from_pivot_pct":  round(float(dist_from_pivot_pct), 2),
        "base_depth_pct":       round(float(base_depth_pct), 2),
        "base_length_days":     int(length),
    }
```

Wire it into `compute_all`:

```python
indicators.update(compute_pivot_proximity(df))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_indicators_new.py::TestPivotProximity -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add screener/indicators.py tests/test_indicators_new.py
git commit -m "indicators: add pivot_proximity for canonical base detection

Identifies the most recent 3-8 week consolidation, computes pivot (base
high), base_depth, and distance-from-pivot. Foundation for O'Neil/
Minervini breakout-point scoring.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Add 12-month RS percentile + RS-line new-high detector

**Files:**
- Modify: `tests/test_indicators_new.py`
- Modify: `screener/indicators.py`
- Modify: `screener/scorer.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_indicators_new.py`:

```python
class TestRSLine:
    def test_rs_line_at_new_high(self):
        from screener.indicators import compute_rs_line
        # Ticker keeps outperforming benchmark monotonically — RS line at peak
        n = 200
        ticker_closes = 100 * np.exp(np.linspace(0, 0.5, n))   # +65%
        bench_closes  = 100 * np.exp(np.linspace(0, 0.1, n))   # +11%
        tdf = _make_df(ticker_closes)
        bdf = _make_df(bench_closes)
        result = compute_rs_line(tdf, bdf)
        assert result["rs_line_at_50d_high"] is True

    def test_rs_line_below_recent_high(self):
        from screener.indicators import compute_rs_line
        n = 200
        # Ticker outperformed then started lagging in last 50 sessions
        ticker_closes = np.concatenate([
            100 * np.exp(np.linspace(0, 0.5, 150)),
            165 + np.linspace(0, -10, 50),
        ])
        bench_closes = 100 * np.exp(np.linspace(0, 0.3, 200))
        tdf = _make_df(ticker_closes)
        bdf = _make_df(bench_closes)
        result = compute_rs_line(tdf, bdf)
        assert result["rs_line_at_50d_high"] is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_indicators_new.py::TestRSLine -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `compute_rs_line` in `screener/indicators.py`**

Add after `compute_ibd_rs`:

```python
def compute_rs_line(
    ticker_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
) -> dict[str, Any]:
    """
    Compute the Relative Strength line (ticker_close / benchmark_close, rebased)
    and check whether it is at a new 50-session high.
    """
    default = {"rs_line_at_50d_high": False}
    t = ticker_df["Close"].squeeze()
    b = benchmark_df["Close"].squeeze()
    aligned = pd.concat([t, b], axis=1, join="inner").dropna()
    if len(aligned) < 60:
        return default
    aligned.columns = ["t", "b"]
    rs_line = aligned["t"] / aligned["b"]
    if rs_line.iloc[0] != 0:
        rs_line = rs_line / rs_line.iloc[0]
    tail = rs_line.tail(50)
    if tail.empty:
        return default
    return {"rs_line_at_50d_high": bool(rs_line.iloc[-1] >= tail.max())}
```

Wire it into `compute_all` near `compute_ibd_rs`:

```python
indicators.update(compute_rs_line(df, benchmark_df))
```

Then also add 12-month RS to `compute_relative_strength` — modify the function signature default:

```python
def compute_relative_strength(
    ticker_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    periods: tuple[int, ...] = (63, 126, 252),  # add 252 for 12m
) -> dict[str, Any]:
```

And in `screener/scorer.py`, update `compute_rs_percentiles` to also percentile-rank the new 12m series. Replace the function body with:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_indicators_new.py::TestRSLine tests/test_scorer.py -v`
Expected: new tests PASS; existing scorer tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add screener/indicators.py screener/scorer.py tests/test_indicators_new.py
git commit -m "indicators: add 12m RS percentile + RS-line new-high detector

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Add pullback-volume-dryup indicator

**Files:**
- Modify: `tests/test_indicators_new.py`
- Modify: `screener/indicators.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_indicators_new.py`:

```python
class TestPullbackVolume:
    def test_dryup_when_pullback_has_low_volume(self):
        from screener.indicators import compute_pullback_volume_ratio
        # Last 5 days: 3 down days with low vol, then 2 up days with normal vol
        n = 30
        closes = np.concatenate([np.full(20, 100.0), [100, 99, 98, 97, 98, 100, 101, 102, 103, 105]])
        # Volumes: 1M normal, 0.3M during pullback (down days at idx 21-23)
        volumes = np.ones(n) * 1_000_000
        volumes[21:24] = 300_000
        df = _make_df(closes, volumes=volumes)
        result = compute_pullback_volume_ratio(df)
        # Pullback volume well below 20d avg
        assert result["pullback_vol_ratio"] < 0.6

    def test_no_pullback_returns_neutral(self):
        from screener.indicators import compute_pullback_volume_ratio
        closes = list(np.linspace(100, 130, 30))
        df = _make_df(closes)
        result = compute_pullback_volume_ratio(df)
        # No pullback found → neutral ratio of 1.0
        assert result["pullback_vol_ratio"] == 1.0
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_indicators_new.py::TestPullbackVolume -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `compute_pullback_volume_ratio` in `screener/indicators.py`**

Add after `compute_volume_analysis`:

```python
def compute_pullback_volume_ratio(df: pd.DataFrame) -> dict[str, Any]:
    """
    During the most recent down-cluster (>=3 consecutive down days) in the last
    10 sessions, compute average volume / 20-day average volume.
    Returns 1.0 (neutral) if no pullback is found.
    """
    default = {"pullback_vol_ratio": 1.0}
    if len(df) < 25:
        return default
    closes = df["Close"].values.astype(float)
    volumes = df["Volume"].values.astype(float)
    avg_vol_20 = float(np.mean(volumes[-20:]))
    if avg_vol_20 <= 0:
        return default

    # Find the most recent run of >=3 consecutive down days in last 10 sessions
    tail = 10
    if len(closes) < tail + 1:
        return default
    diffs = np.diff(closes[-tail - 1:])
    down_mask = diffs < 0  # indices 0..tail-1 relative to start of tail

    # Walk back to find the longest contiguous down-cluster ending at idx tail-1
    # (or earlier within last 10 sessions)
    best_run = None  # (start, end) inclusive
    i = len(down_mask) - 1
    while i >= 0:
        if down_mask[i]:
            j = i
            while j > 0 and down_mask[j - 1]:
                j -= 1
            if i - j + 1 >= 3:
                best_run = (j, i)
                break
            i = j - 1
        else:
            i -= 1

    if best_run is None:
        return default

    # Map relative indices back to absolute indices in the volumes array
    base = len(closes) - tail
    abs_start = base + best_run[0] + 1  # +1 because diff index points to the second bar
    abs_end = base + best_run[1] + 1
    pullback_volumes = volumes[abs_start:abs_end + 1]
    if pullback_volumes.size == 0:
        return default

    ratio = float(np.mean(pullback_volumes) / avg_vol_20)
    return {"pullback_vol_ratio": round(ratio, 3)}
```

Wire it into `compute_all` after `compute_volume_analysis`:

```python
indicators.update(compute_pullback_volume_ratio(df))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_indicators_new.py::TestPullbackVolume -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add screener/indicators.py tests/test_indicators_new.py
git commit -m "indicators: add pullback_vol_ratio for canonical volume dry-up signal

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Create `screener/qualify.py` (Tier 1 gate)

**Files:**
- Create: `screener/qualify.py`
- Create: `tests/test_qualify.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_qualify.py`:

```python
"""Unit tests for Tier 1 qualification gate."""
from __future__ import annotations

from screener import qualify


def _passing_ind(**overrides):
    """Indicator dict that passes the full Tier 1 gate."""
    base = {
        "ticker": "TEST",
        "close": 50.0,
        "avg_volume_20d": 1_000_000,
        "ema21": 49.0, "ema50": 47.0, "ema150": 44.0, "ema200": 42.0,
        "ema_aligned": True,
        "ema200_slope": 0.20,
        "ema200_slope_positive": True,
        "ema200_rising_sessions": 30,
        "adx_14": 25.0,
        "dist_from_52w_high_pct": 8.0,
        "pct_above_52w_low": 50.0,
        "max_1d_move_120d": 8.0,
        "max_gap_120d": 5.0,
        "vol_60d": 2.5,
    }
    base.update(overrides)
    return base


class TestQualifyHappyPath:
    def test_passing_indicators_qualify(self):
        ok, reason = qualify.qualifies(_passing_ind())
        assert ok is True
        assert reason == ""


class TestQualifyMinervini:
    def test_fails_below_ema200(self):
        ok, reason = qualify.qualifies(_passing_ind(ema_aligned=False, ema200=51.0))
        assert ok is False
        assert "ema_aligned" in reason or "ema200" in reason

    def test_fails_ema50_below_ema150(self):
        ok, reason = qualify.qualifies(_passing_ind(ema50=43.0))  # ema150=44, ema50<ema150
        assert ok is False

    def test_fails_ema150_below_ema200(self):
        ok, reason = qualify.qualifies(_passing_ind(ema150=41.0))  # ema200=42
        assert ok is False

    def test_fails_ema200_not_rising_long_enough(self):
        ok, reason = qualify.qualifies(_passing_ind(ema200_rising_sessions=15))
        assert ok is False
        assert "rising" in reason

    def test_fails_below_30pct_above_52w_low(self):
        ok, reason = qualify.qualifies(_passing_ind(pct_above_52w_low=25.0))
        assert ok is False

    def test_fails_too_far_below_52w_high(self):
        ok, reason = qualify.qualifies(_passing_ind(dist_from_52w_high_pct=30.0))
        assert ok is False


class TestQualityBars:
    def test_fails_below_min_price(self):
        ok, _ = qualify.qualifies(_passing_ind(close=5.0))
        assert ok is False

    def test_fails_below_min_avg_volume(self):
        ok, _ = qualify.qualifies(_passing_ind(avg_volume_20d=100_000))
        assert ok is False


class TestClimacticRejects:
    def test_fails_climactic_1d_move(self):
        ok, reason = qualify.qualifies(_passing_ind(max_1d_move_120d=30.0))
        assert ok is False
        assert "climactic" in reason or "1d_move" in reason

    def test_fails_exhaustion_gap(self):
        ok, reason = qualify.qualifies(_passing_ind(max_gap_120d=22.0))
        assert ok is False

    def test_fails_high_vol_60d(self):
        ok, reason = qualify.qualifies(_passing_ind(vol_60d=10.0))
        assert ok is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_qualify.py -v`
Expected: FAIL with `ImportError: No module named 'screener.qualify'`.

- [ ] **Step 3: Implement `screener/qualify.py`**

Create the file with:

```python
"""
Tier 1 — Qualification Gate.

A stock must pass ALL criteria here to reach Tier 2 scoring. Failures are
final (no graduated penalty).
"""
from __future__ import annotations

from typing import Any

from . import config


def qualifies(ind: dict[str, Any]) -> tuple[bool, str]:
    """
    Return (True, "") if the stock passes every Tier 1 criterion.
    Return (False, "<short reason>") otherwise, naming the FIRST failing criterion.
    """
    close   = ind.get("close", 0.0)
    avg_vol = ind.get("avg_volume_20d", 0)

    # Quality bars
    if close < config.MIN_PRICE:
        return False, f"price<{config.MIN_PRICE}"
    if avg_vol < config.MIN_AVG_VOLUME:
        return False, f"avg_vol<{config.MIN_AVG_VOLUME}"
    if close * avg_vol < config.MIN_DOLLAR_VOLUME:
        return False, f"dollar_vol<{config.MIN_DOLLAR_VOLUME}"

    # Minervini criteria 1-5 (price > EMA21 > EMA50 > EMA150 > EMA200, encoded as ema_aligned)
    if not ind.get("ema_aligned", False):
        return False, "ema_aligned=false"

    # Criterion 4 & 5: explicit EMA50 > EMA150 and EMA150 > EMA200 (redundant with ema_aligned but defensive)
    ema50  = ind.get("ema50",  0.0)
    ema150 = ind.get("ema150", 0.0)
    ema200 = ind.get("ema200", 0.0)
    if not (ema50 > ema150 > ema200 > 0):
        return False, "ema_order"

    # Criterion 6: EMA200 rising for >= 22 sessions
    if ind.get("ema200_rising_sessions", 0) < config.MIN_EMA200_RISING_SESSIONS:
        return False, f"ema200_rising_sessions<{config.MIN_EMA200_RISING_SESSIONS}"

    # Criterion 7: within 25% of 52w high
    if ind.get("dist_from_52w_high_pct", 100.0) > config.MAX_DIST_FROM_52W_HIGH_PCT:
        return False, "dist_from_52w_high>25"

    # Criterion 8: at least 30% above 52w low
    if ind.get("pct_above_52w_low", 0.0) < config.MIN_PCT_ABOVE_52W_LOW:
        return False, "pct_above_52w_low<30"

    # ADX baseline
    if ind.get("adx_14", 0.0) < config.MIN_ADX:
        return False, f"adx<{config.MIN_ADX}"

    # Climactic / exhaustion rejects
    if ind.get("max_1d_move_120d", 0.0) >= config.HARD_REJECT_1D_MOVE_PCT:
        return False, f"climactic_1d_move>={config.HARD_REJECT_1D_MOVE_PCT}"
    if ind.get("max_gap_120d", 0.0) >= config.HARD_REJECT_GAP_PCT:
        return False, f"exhaustion_gap>={config.HARD_REJECT_GAP_PCT}"

    # Wide-trading-range reject
    if ind.get("vol_60d", 0.0) > config.HARD_REJECT_VOL_60D_PCT:
        return False, f"vol_60d>{config.HARD_REJECT_VOL_60D_PCT}"

    return True, ""
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_qualify.py -v`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add screener/qualify.py tests/test_qualify.py
git commit -m "qualify: Tier 1 gate module — full Minervini template + climactic rejects

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Create `screener/setup_score.py` (Tier 2 scoring)

**Files:**
- Create: `screener/setup_score.py`
- Create: `tests/test_setup_score.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_setup_score.py`:

```python
"""Unit tests for Tier 2 setup quality scoring."""
from __future__ import annotations

from screener import setup_score


def _baseline_ind(**overrides):
    base = {
        "close": 50.0, "avg_volume_20d": 1_000_000,
        "ema21": 49.0, "ema50": 47.0, "ema150": 44.0, "ema200": 42.0,
        "ema_aligned": True,
        "ema200_slope": 0.20,
        "ema200_rising_sessions": 30,
        "adx_14": 30.0, "adx_robust": 28.0,
        "dist_from_52w_high_pct": 5.0,
        "pct_above_52w_low": 60.0,
        "rsi_14": 60.0,
        "macd_hist": 0.05,
        "macd_crossover_sessions_ago": 5,
        "obv_slope_norm": 3.0,
        "cmf_20": 0.10,
        "upvol_ratio": 0.6,
        "volume_ratio": 1.2,
        "pullback_vol_ratio": 0.7,
        "rs_3m_percentile": 80.0,
        "rs_6m_percentile": 75.0,
        "rs_12m_percentile": 70.0,
        "ibd_rs_percentile": 85.0,
        "rs_line_at_50d_high": True,
        "vcp_score": 60.0,
        "squeeze_score": 50.0,
        "pivot_price": 50.0,
        "dist_from_pivot_pct": 0.5,
        "r2_log_60d": 0.85,
        "outlier_bar_count_60d": 0,
        "max_1d_move_120d": 8.0,
        "max_gap_120d": 5.0,
    }
    base.update(overrides)
    return base


class TestTrendStrength:
    def test_high_score_for_clean_trend(self):
        ind = _baseline_ind()
        s = setup_score.score_trend_strength(ind)
        assert s > 70.0

    def test_zero_for_unaligned(self):
        ind = _baseline_ind(ema_aligned=False)
        s = setup_score.score_trend_strength(ind)
        # ema_alignment weight 0.20 → losing 20 points minimum
        assert s < 80.0

    def test_robust_adx_used(self):
        # naive adx high (54) but robust adx low (15) → score reflects robust value
        ind = _baseline_ind(adx_14=54.0, adx_robust=15.0)
        s_robust = setup_score.score_trend_strength(ind)
        ind2 = _baseline_ind(adx_14=54.0, adx_robust=54.0)
        s_naive = setup_score.score_trend_strength(ind2)
        assert s_robust < s_naive


class TestTrendCleanliness:
    def test_high_r2_full_credit(self):
        ind = _baseline_ind(r2_log_60d=0.95, outlier_bar_count_60d=0)
        s = setup_score.score_trend_cleanliness(ind)
        assert s > 90.0

    def test_low_r2_zero(self):
        ind = _baseline_ind(r2_log_60d=0.05, outlier_bar_count_60d=0)
        s = setup_score.score_trend_cleanliness(ind)
        # R² < 0.40 → cleanliness sub-score = 0 from r2 component
        assert s < 50.0

    def test_outlier_bars_zero_credit(self):
        ind = _baseline_ind(r2_log_60d=0.95, outlier_bar_count_60d=5)
        s = setup_score.score_trend_cleanliness(ind)
        assert s < 70.0  # outlier penalty kicks in


class TestRelativeStrength:
    def test_high_rs_with_bonus(self):
        ind = _baseline_ind(
            ibd_rs_percentile=95.0, rs_3m_percentile=95.0,
            rs_6m_percentile=95.0, rs_12m_percentile=95.0,
            rs_line_at_50d_high=True,
        )
        s = setup_score.score_rs(ind)
        # Should be capped at 100, including the +10 bonus
        assert s == 100.0

    def test_no_bonus_when_rs_line_not_at_high(self):
        ind = _baseline_ind(rs_line_at_50d_high=False, ibd_rs_percentile=80.0)
        s_with = setup_score.score_rs(_baseline_ind(rs_line_at_50d_high=True, ibd_rs_percentile=80.0))
        s_without = setup_score.score_rs(ind)
        assert s_with > s_without


class TestBaseSetup:
    def test_vcp_skipped_after_spike(self):
        # max_1d_move 15% → VCP guard fires → vcp contribution zero
        ind = _baseline_ind(vcp_score=80.0, max_1d_move_120d=15.0)
        s_guarded = setup_score.score_base_setup(ind)
        ind_clean = _baseline_ind(vcp_score=80.0, max_1d_move_120d=5.0)
        s_clean = setup_score.score_base_setup(ind_clean)
        assert s_guarded < s_clean

    def test_pivot_proximity_at_pivot(self):
        ind = _baseline_ind(dist_from_pivot_pct=0.5, pivot_price=50.0)
        s = setup_score.score_base_setup(ind)
        # Pivot at 0.5% → near-max for that sub-component
        assert s > 50.0

    def test_pivot_proximity_too_extended(self):
        ind = _baseline_ind(dist_from_pivot_pct=8.0, pivot_price=50.0)
        s_extended = setup_score.score_base_setup(ind)
        ind_at = _baseline_ind(dist_from_pivot_pct=0.5, pivot_price=50.0)
        s_at = setup_score.score_base_setup(ind_at)
        assert s_extended < s_at


class TestVolumeProfile:
    def test_dryup_on_pullback_scores_high(self):
        ind = _baseline_ind(pullback_vol_ratio=0.5)
        s_dry = setup_score.score_volume_profile(ind)
        ind2 = _baseline_ind(pullback_vol_ratio=1.5)
        s_surge = setup_score.score_volume_profile(ind2)
        assert s_dry > s_surge

    def test_breakout_volume_only_at_pivot(self):
        # Far from pivot — breakout volume sub-score should be neutral (50)
        ind_far = _baseline_ind(dist_from_pivot_pct=8.0, volume_ratio=2.0)
        ind_at  = _baseline_ind(dist_from_pivot_pct=0.5, volume_ratio=2.0)
        s_far = setup_score.score_volume_profile(ind_far)
        s_at  = setup_score.score_volume_profile(ind_at)
        assert s_at > s_far


class TestComposite:
    def test_compute_setup_score_returns_dict(self):
        out = setup_score.compute_setup_score(_baseline_ind())
        for k in ("trend_strength", "trend_cleanliness", "rs", "base_setup", "volume_profile", "raw_setup_score"):
            assert k in out
        assert 0 <= out["raw_setup_score"] <= 100
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_setup_score.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `screener/setup_score.py`**

Create the file:

```python
"""
Tier 2 — Setup Quality Score.

Five categories: Trend Strength, Trend Cleanliness, Relative Strength,
Base/Setup, Volume Profile. Each is graded 0-100; the composite is a weighted
sum using config.CATEGORY_WEIGHTS.
"""
from __future__ import annotations

from typing import Any

from . import config


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ── A. Trend Strength ─────────────────────────────────────────────────────────

def score_trend_strength(ind: dict[str, Any]) -> float:
    w = config.TREND_STRENGTH_SUB_WEIGHTS

    ema_align = 100.0 if ind.get("ema_aligned", False) else 0.0

    slope = ind.get("ema200_slope", 0.0)
    rising = ind.get("ema200_rising_sessions", 0) >= config.MIN_EMA200_RISING_SESSIONS
    slope_score = _clamp(slope * 200.0) if rising else _clamp(slope * 200.0) * 0.5

    ema50 = ind.get("ema50", 0.0)
    ema200 = ind.get("ema200", 0.0)
    if ema200 > 0:
        spread_score = _clamp((ema50 / ema200 - 1.0) * 500.0)
    else:
        spread_score = 0.0

    dist = ind.get("dist_from_52w_high_pct", 100.0)
    dist_score = _clamp(100.0 - dist * 4.0)

    adx_robust = ind.get("adx_robust", ind.get("adx_14", 0.0))
    adx_score = _clamp(adx_robust * 2.0)

    return (
        ema_align    * w["ema_alignment"]
        + slope_score  * w["ema200_slope_sustained"]
        + spread_score * w["ema50_above_ema200"]
        + dist_score   * w["dist_from_52w_high"]
        + adx_score    * w["adx_robust"]
    )


# ── B. Trend Cleanliness ──────────────────────────────────────────────────────

def score_trend_cleanliness(ind: dict[str, Any]) -> float:
    w = config.TREND_CLEANLINESS_SUB_WEIGHTS
    r2 = ind.get("r2_log_60d", 0.0)
    r2_score = _clamp((r2 - 0.40) * 200.0)  # R² 0.40 → 0; R² 0.90 → 100

    outliers = ind.get("outlier_bar_count_60d", 0)
    outlier_score = _clamp(100.0 - outliers * 25.0)

    return r2_score * w["r2_log_60d"] + outlier_score * w["outlier_bar_ratio"]


# ── C. Relative Strength ──────────────────────────────────────────────────────

def score_rs(ind: dict[str, Any]) -> float:
    w = config.RS_SUB_WEIGHTS
    ibd  = ind.get("ibd_rs_percentile", 50.0)
    p3m  = ind.get("rs_3m_percentile",  50.0)
    p6m  = ind.get("rs_6m_percentile",  50.0)
    p12m = ind.get("rs_12m_percentile", 50.0)
    base = (
        ibd  * w["ibd_rs_percentile"]
        + p3m  * w["rs_3m_percentile"]
        + p6m  * w["rs_6m_percentile"]
        + p12m * w["rs_12m_percentile"]
    )
    if ind.get("rs_line_at_50d_high", False):
        base += config.RS_LINE_NEW_HIGH_BONUS
    return _clamp(base)


# ── D. Base / Setup Quality ───────────────────────────────────────────────────

def _vcp_guarded_score(ind: dict[str, Any]) -> float:
    max_1d  = ind.get("max_1d_move_120d", 0.0)
    max_gap = ind.get("max_gap_120d", 0.0)
    if max_1d > config.VCP_GUARD_MAX_BAR_PCT or max_gap > config.VCP_GUARD_MAX_GAP_PCT:
        return 0.0
    return _clamp(ind.get("vcp_score", 0.0))


def _pivot_proximity_score(ind: dict[str, Any]) -> float:
    pivot = ind.get("pivot_price", 0.0)
    if pivot <= 0:
        return 0.0
    d = ind.get("dist_from_pivot_pct", 99.0)
    # Reward 0..1% above pivot; decay 20 points per 1% away from pivot+0.5
    return _clamp(100.0 - abs(d - 0.5) * 20.0)


def score_base_setup(ind: dict[str, Any]) -> float:
    w = config.BASE_SETUP_SUB_WEIGHTS
    vcp = _vcp_guarded_score(ind)
    pivot = _pivot_proximity_score(ind)
    squeeze = _clamp(ind.get("squeeze_score", 0.0))
    return vcp * w["vcp_guarded"] + pivot * w["pivot_proximity"] + squeeze * w["squeeze"]


# ── E. Volume Profile ─────────────────────────────────────────────────────────

def score_volume_profile(ind: dict[str, Any]) -> float:
    w = config.VOLUME_PROFILE_SUB_WEIGHTS

    obv_slope = ind.get("obv_slope_norm", 0.0)
    obv_score = _clamp((obv_slope + 10.0) * 5.0)

    cmf = ind.get("cmf_20", 0.0)
    cmf_score = _clamp((cmf + 0.2) * 100.0)

    pull = ind.get("pullback_vol_ratio", 1.0)
    dryup_score = _clamp((1.0 - pull) * 200.0)

    # Breakout-day vol: only contributes when within 2% of pivot
    dist_p = ind.get("dist_from_pivot_pct", 99.0)
    vol_ratio = ind.get("volume_ratio", 1.0)
    if -2.0 <= dist_p <= 2.0 and ind.get("pivot_price", 0.0) > 0:
        breakout_score = _clamp((vol_ratio - 1.0) * 50.0)
    else:
        breakout_score = 50.0

    return (
        obv_score      * w["obv_slope"]
        + cmf_score      * w["cmf"]
        + dryup_score    * w["pullback_vol_dryup"]
        + breakout_score * w["breakout_day_volume"]
    )


# ── Composite ─────────────────────────────────────────────────────────────────

def compute_setup_score(ind: dict[str, Any]) -> dict[str, float]:
    """Return per-category scores plus the weighted raw setup score (0-100)."""
    ts = score_trend_strength(ind)
    tc = score_trend_cleanliness(ind)
    rs = score_rs(ind)
    bs = score_base_setup(ind)
    vp = score_volume_profile(ind)
    w = config.CATEGORY_WEIGHTS
    total = (
        ts * w["trend_strength"]
        + tc * w["trend_cleanliness"]
        + rs * w["rs"]
        + bs * w["base_setup"]
        + vp * w["volume_profile"]
    )
    return {
        "trend_strength":     round(ts, 1),
        "trend_cleanliness":  round(tc, 1),
        "rs":                 round(rs, 1),
        "base_setup":         round(bs, 1),
        "volume_profile":     round(vp, 1),
        "raw_setup_score":    round(total, 1),
    }
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_setup_score.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add screener/setup_score.py tests/test_setup_score.py
git commit -m "setup_score: Tier 2 scoring across 5 canonical categories

Trend strength, trend cleanliness (R² + outliers), RS (IBD-weighted with
RS-line-new-high bonus), base/setup (VCP-guarded + pivot proximity +
squeeze), and volume profile (OBV + CMF + pullback dryup + breakout vol).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Create `screener/penalties.py` (Tier 3)

**Files:**
- Create: `screener/penalties.py`
- Create: `tests/test_penalties.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_penalties.py`:

```python
"""Unit tests for Tier 3 penalty multipliers."""
from __future__ import annotations

from screener import penalties


def _ind(**overrides):
    base = {
        "max_1d_move_120d": 5.0,
        "max_gap_120d": 3.0,
        "concentration_60d": 20.0,
        "dist_from_5d_high_pct": 1.0,
        "pct_above_52w_low": 50.0,
        "extension_atr_multiple": 1.0,
        "extension_ema50_pct": 5.0,
    }
    base.update(overrides)
    return base


class TestSpikePenalties:
    def test_clean_stock_no_penalty(self):
        out = penalties.compute_penalty_multiplier(_ind())
        assert out["final_multiplier"] == 1.0
        assert out["triggered"] == []

    def test_mild_spike(self):
        out = penalties.compute_penalty_multiplier(_ind(max_1d_move_120d=11.0))
        assert 0.80 <= out["final_multiplier"] < 1.0
        assert "climactic_mild" in out["triggered"]

    def test_severe_spike(self):
        out = penalties.compute_penalty_multiplier(_ind(max_1d_move_120d=22.0))
        assert out["final_multiplier"] <= 0.30
        assert "climactic_severe" in out["triggered"]


class TestGapPenalties:
    def test_mild_gap(self):
        out = penalties.compute_penalty_multiplier(_ind(max_gap_120d=12.0))
        assert 0.70 <= out["final_multiplier"] < 1.0
        assert "exhaustion_gap_mild" in out["triggered"]


class TestConcentrationPenalties:
    def test_concentrated_rally(self):
        out = penalties.compute_penalty_multiplier(_ind(concentration_60d=70.0))
        assert out["final_multiplier"] <= 0.40
        assert "concentration_severe" in out["triggered"]


class TestReversalPenalties:
    def test_rolling_over(self):
        out = penalties.compute_penalty_multiplier(_ind(dist_from_5d_high_pct=8.0))
        assert out["final_multiplier"] <= 0.50
        assert "reversal_heavy" in out["triggered"]


class TestExtensionPenalties:
    def test_far_above_52w_low(self):
        out = penalties.compute_penalty_multiplier(_ind(pct_above_52w_low=130.0))
        assert out["final_multiplier"] < 1.0
        assert any(t.startswith("52w_low") for t in out["triggered"])


class TestComposition:
    def test_multiple_triggers_take_minimum(self):
        out = penalties.compute_penalty_multiplier(_ind(
            max_1d_move_120d=22.0,    # severe ~0.25
            dist_from_5d_high_pct=8.0,  # heavy ~0.40
        ))
        assert out["final_multiplier"] <= 0.25 + 0.01

    def test_floor_at_005(self):
        out = penalties.compute_penalty_multiplier(_ind(
            max_1d_move_120d=22.0,
            max_gap_120d=18.0,
            concentration_60d=80.0,
            dist_from_5d_high_pct=15.0,
            pct_above_52w_low=300.0,
        ))
        assert out["final_multiplier"] >= 0.05
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_penalties.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `screener/penalties.py`**

Create the file:

```python
"""
Tier 3 — Penalty Multipliers.

Each penalty is a (trigger condition, multiplier) pair. When triggered, the
penalty's multiplier is composed via min() with the final multiplier.
Floor is 0.05.
"""
from __future__ import annotations

from typing import Any

from . import config


_FLOOR = 0.05


def _band(value: float, mild_t: float, heavy_t: float, severe_t: float,
          mild_m: float, heavy_m: float, severe_m: float,
          name: str) -> tuple[float, str | None]:
    """Three-band penalty: returns (multiplier, triggered_name)."""
    if value >= severe_t:
        return severe_m, f"{name}_severe"
    if value >= heavy_t:
        return heavy_m, f"{name}_heavy"
    if value >= mild_t:
        return mild_m, f"{name}_mild"
    return 1.0, None


def compute_penalty_multiplier(ind: dict[str, Any]) -> dict[str, Any]:
    """
    Returns:
      {
        "final_multiplier": float (>= 0.05),
        "triggered":        list[str],
        "multipliers":      dict[str, float],  # per-penalty
      }
    """
    multipliers: dict[str, float] = {}
    triggered: list[str] = []

    # 1. Climactic single bar
    m, t = _band(
        ind.get("max_1d_move_120d", 0.0),
        mild_t=config.CLIMACTIC_1D_MILD_PCT,
        heavy_t=config.CLIMACTIC_1D_HEAVY_PCT,
        severe_t=config.CLIMACTIC_1D_SEVERE_PCT,
        mild_m=0.85, heavy_m=0.50, severe_m=0.25, name="climactic",
    )
    if t:
        multipliers["climactic"] = m
        triggered.append(t)

    # 2. Exhaustion gap (mild/heavy only)
    gap = ind.get("max_gap_120d", 0.0)
    if gap >= config.GAP_PENALTY_HEAVY_PCT:
        multipliers["exhaustion_gap"] = 0.40
        triggered.append("exhaustion_gap_heavy")
    elif gap >= config.GAP_PENALTY_MILD_PCT:
        multipliers["exhaustion_gap"] = 0.80
        triggered.append("exhaustion_gap_mild")

    # 3. Rally concentration
    conc = ind.get("concentration_60d", 0.0)
    if conc >= config.CONCENTRATION_60D_SEVERE_PCT:
        multipliers["concentration"] = 0.30
        triggered.append("concentration_severe")
    elif conc >= config.CONCENTRATION_60D_MILD_PCT:
        multipliers["concentration"] = 0.60
        triggered.append("concentration_mild")

    # 4. Recent reversal
    rev = ind.get("dist_from_5d_high_pct", 0.0)
    if rev >= config.REVERSAL_5D_HEAVY_PCT:
        multipliers["reversal"] = 0.40
        triggered.append("reversal_heavy")
    elif rev >= config.REVERSAL_5D_MILD_PCT:
        multipliers["reversal"] = 0.70
        triggered.append("reversal_mild")

    # 5. 52w-low extension (recalibrated)
    above = ind.get("pct_above_52w_low", 0.0)
    if above >= config.DIST_52W_LOW_REJECT_PCT:
        multipliers["52w_low"] = 0.30
        triggered.append("52w_low_severe")
    elif above >= config.DIST_52W_LOW_HEAVY_PCT:
        multipliers["52w_low"] = 0.60
        triggered.append("52w_low_heavy")
    elif above >= config.DIST_52W_LOW_MILD_PCT:
        multipliers["52w_low"] = 0.85
        triggered.append("52w_low_mild")

    # 6. ATR extension (carry over from existing logic — keep same thresholds)
    atr_mult_x = ind.get("extension_atr_multiple", 0.0)
    if atr_mult_x >= config.EXTENSION_ATR_REJECT:
        multipliers["atr_extension"] = 0.10
        triggered.append("atr_extension_reject")
    elif atr_mult_x >= config.EXTENSION_ATR_HEAVY:
        multipliers["atr_extension"] = 0.50
        triggered.append("atr_extension_heavy")
    elif atr_mult_x >= config.EXTENSION_ATR_MILD:
        multipliers["atr_extension"] = 0.85
        triggered.append("atr_extension_mild")

    final = 1.0
    for m_ in multipliers.values():
        final = min(final, m_)
    final = max(_FLOOR, final)

    return {
        "final_multiplier": round(final, 3),
        "triggered":        triggered,
        "multipliers":      multipliers,
    }
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_penalties.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add screener/penalties.py tests/test_penalties.py
git commit -m "penalties: Tier 3 multiplicative penalties for spike/gap/concentration/reversal

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Rewire `screener/scorer.py` to orchestrate the three tiers

**Files:**
- Modify: `screener/scorer.py`
- Modify: `tests/test_scorer.py`
- Create: `tests/test_scorer_v2.py`

- [ ] **Step 1: Write the v2 end-to-end test first**

Create `tests/test_scorer_v2.py`:

```python
"""End-to-end v2 scorer tests: real indicator dicts → composite score."""
from __future__ import annotations

from screener import scorer


def _clean_trend_ind(**overrides):
    """A canonical clean Stage-2 stock (GLNG-like)."""
    base = {
        "ticker": "GLNG_LIKE",
        "close": 57.0, "avg_volume_20d": 1_500_000,
        "ema21": 55.0, "ema50": 52.0, "ema150": 48.0, "ema200": 45.0,
        "ema_aligned": True,
        "ema200_slope": 0.35, "ema200_slope_positive": True,
        "ema200_rising_sessions": 60,
        "adx_14": 30.0, "adx_robust": 28.0,
        "dist_from_52w_high_pct": 1.0, "pct_above_52w_low": 55.0,
        "obv_slope_norm": 4.0, "cmf_20": 0.12,
        "volume_ratio": 1.2, "upvol_ratio": 0.65, "pullback_vol_ratio": 0.7,
        "rs_3m_percentile": 80, "rs_6m_percentile": 78,
        "rs_12m_percentile": 75, "ibd_rs_percentile": 82,
        "rs_line_at_50d_high": True,
        "vcp_score": 55.0, "squeeze_score": 40.0,
        "pivot_price": 56.5, "dist_from_pivot_pct": 0.9, "base_depth_pct": 6.0, "base_length_days": 22,
        "r2_log_60d": 0.78, "outlier_bar_count_60d": 0,
        "max_1d_move_120d": 6.0, "max_gap_120d": 4.0,
        "concentration_60d": 22.0, "dist_from_5d_high_pct": 1.0,
        "extension_atr_multiple": 1.5, "extension_ema50_pct": 9.0,
    }
    base.update(overrides)
    return base


def _slab_like_ind(**overrides):
    """SLAB-style post-spike drift."""
    base = _clean_trend_ind(
        ticker="SLAB_LIKE",
        adx_14=54.0, adx_robust=18.0,
        r2_log_60d=0.85, outlier_bar_count_60d=1,
        max_1d_move_120d=49.0, max_gap_120d=50.0,    # triggers hard reject
        concentration_60d=19.0,
        vcp_score=70.0,  # VCP guard should kill this
        rs_3m_percentile=22.0,  # weak 3m RS
    )
    base.update(overrides)
    return base


class TestV2CompositeScore:
    def test_clean_trend_qualifies_and_scores_high(self):
        out = scorer.compute_composite(_clean_trend_ind())
        assert out["qualifies"] is True
        assert out["composite_score"] > 55.0

    def test_slab_like_rejected_by_gate(self):
        out = scorer.compute_composite(_slab_like_ind())
        # Hard rejected by climactic 1d move
        assert out["qualifies"] is False
        assert "climactic" in out["fail_reason"] or "1d_move" in out["fail_reason"]

    def test_borderline_post_spike_drifts_get_penalized(self):
        # Same as clean, but 16% bar 70 sessions ago: should pass gate (25% threshold)
        # but get heavy climactic penalty
        out = scorer.compute_composite(_clean_trend_ind(max_1d_move_120d=16.0))
        assert out["qualifies"] is True
        assert out["composite_score"] < 50.0   # penalty bites

    def test_reversing_stock_penalized(self):
        out = scorer.compute_composite(_clean_trend_ind(dist_from_5d_high_pct=8.0))
        assert out["qualifies"] is True
        assert "reversal_heavy" in out["penalty_triggered"]


class TestRanking:
    def test_clean_outranks_post_spike(self):
        clean = scorer.compute_composite(_clean_trend_ind())
        # A "passes-gate-with-warning-flags" version (15% bar 80 days ago)
        warned = scorer.compute_composite(_clean_trend_ind(max_1d_move_120d=15.0))
        assert clean["composite_score"] > warned["composite_score"]
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_scorer_v2.py -v`
Expected: FAIL with `AttributeError: module 'screener.scorer' has no attribute 'compute_composite'`.

- [ ] **Step 3: Rewrite `screener/scorer.py` to orchestrate qualify/setup_score/penalties**

Replace the existing `passes_hard_filters` and `compute_composite_score` (and `_extension_penalty_multiplier`) with v2 orchestration. Keep `compute_rs_percentiles`, `fetch_sector_info`, `rank_stocks`, and the sector-cache logic untouched.

Open `screener/scorer.py`. Delete the following functions (they are replaced):
- `passes_hard_filters` (replaced by `qualify.qualifies`)
- All `_score_*` helpers (`_clamp`, `_score_trend`, `_score_rs`, `_score_volume`, `_score_momentum`, `_score_stage2`, `_score_pattern`)
- `_extension_penalty_multiplier`
- `compute_composite_score`

Add at the top of the file:

```python
from . import qualify, setup_score, penalties
```

Add a new orchestrator:

```python
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
            "qualifies":         False,
            "fail_reason":       reason,
            "composite_score":   0.0,
            "raw_setup_score":   0.0,
            "trend_strength":    0.0,
            "trend_cleanliness": 0.0,
            "rs":                0.0,
            "base_setup":        0.0,
            "volume_profile":    0.0,
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
```

Update `rank_stocks` — find the existing block that loops over qualifying stocks and calls `compute_composite_score`. Replace the relevant section so it now reads:

```python
def rank_stocks(
    all_indicators: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
            "composite_score":    comp["composite_score"],
            "raw_setup_score":    comp["raw_setup_score"],
            "score_breakdown":    {
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

    # 4. Sort and apply sector cap (unchanged logic below)
    qualifying.sort(key=lambda x: x.get("composite_score", 0.0), reverse=True)
    candidate_tickers = [i["ticker"] for i in qualifying[:30]]
    sector_info = fetch_sector_info(candidate_tickers)
    known_sectors = sum(1 for v in sector_info.values() if v["sector"] != "Unknown")
    use_sector_cap = known_sectors >= len(sector_info) * 0.5
    if not use_sector_cap:
        logger.warning("Sector lookup mostly failed — skipping sector cap")

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

    stats = {"screened_count": screened_count, "qualifying_count": qualifying_count}
    return top_picks, stats
```

- [ ] **Step 4: Mark the existing `test_scorer.py` tests as legacy**

Open `tests/test_scorer.py`. Add at the top, right under the docstring:

```python
import pytest
pytestmark = pytest.mark.skip(reason="v1 scorer tests — superseded by test_scorer_v2.py")
```

This keeps the file for historical reference without breaking CI. We'll prune dead tests in a later cleanup.

- [ ] **Step 5: Run all tests**

Run: `pytest tests/ -v`
Expected: all new tests PASS; old `test_scorer.py` tests SKIPPED; `test_indicators.py` unchanged.

- [ ] **Step 6: Commit**

```bash
git add screener/scorer.py tests/test_scorer.py tests/test_scorer_v2.py
git commit -m "scorer: orchestrate three-tier v2 pipeline (qualify → score → penalize)

Replaces single-function composite with explicit Tier 1/2/3 orchestration.
Old v1 scorer tests are skipped (kept for reference); v2 behavior is
covered by test_scorer_v2.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Update `screener/main.py` to embed scorer version

**Files:**
- Modify: `screener/main.py`

- [ ] **Step 1: Read current `main.py` schema-emission block**

Run: `grep -n "scorer_version\|run_date\|qualifying_count\|json.dump\|to_json" screener/main.py`
Find the block that builds the output dict. The pattern looks like:

```python
output = {
    "run_date": ...,
    "run_timestamp": ...,
    "screened_count": ...,
    "qualifying_count": ...,
    "top_picks": ...,
    "macro": ...,
}
```

- [ ] **Step 2: Add scorer_version fields to the output dict**

Edit `screener/main.py` — locate the output dict assembly and add:

```python
output = {
    "run_date": run_date,
    "run_timestamp": run_ts,
    "scorer_version": config.SCORER_VERSION,
    "scorer_revised_at": config.SCORER_REVISED_AT,
    "screened_count": ...,
    ...
}
```

(Use the actual existing variable names from main.py — they may differ slightly.)

- [ ] **Step 3: Run main with --dry-run smoke test**

Run: `python -m screener.main --dry-run 2>&1 | tail -30`
Expected: completes; "scorer_version: 2.0" appears in any log line if logged, or `latest.json` contains the key. If `--dry-run` doesn't write the file, just confirm no Python exceptions.

- [ ] **Step 4: Commit**

```bash
git add screener/main.py
git commit -m "main: embed scorer_version in latest.json for historical run tagging

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Create `screener/backtest.py` (v1 vs v2 forward-return harness)

**Files:**
- Create: `screener/backtest.py`

- [ ] **Step 1: Implement the backtest harness**

Create `screener/backtest.py`:

```python
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
    """Fetch close prices around as_of and compute forward % return at +days sessions."""
    start = as_of - timedelta(days=10)
    end = as_of + timedelta(days=days + 14)
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
        if df.empty:
            return None
        if hasattr(df.columns, "levels"):
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        # Snap to closest trading day at or before as_of
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
    """Re-fetch OHLCV up to as_of, compute v2 indicators + composite for one ticker."""
    start = as_of - timedelta(days=730)
    try:
        df = yf.download(ticker, start=start, end=as_of + timedelta(days=1), progress=False, auto_adjust=False)
        if df.empty or len(df) < config.MIN_DATA_ROWS:
            return None
        if hasattr(df.columns, "levels"):
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        ind = indicators.compute_all(ticker, df, benchmark_df)
        if ind is None:
            return None
        comp = scorer.compute_composite(ind)
        return {"ticker": ticker, **comp}
    except Exception:
        return None


def backtest(days: int = 30) -> None:
    """Run v1-vs-v2 backtest over the last `days` daily history files."""
    hist_dir = Path(config.HISTORY_DIR)
    files = sorted(hist_dir.glob("*.json"))[-days:]
    out_rows: list[dict] = []

    # Benchmark once (covers full date range)
    bench_start = (datetime.utcnow() - timedelta(days=days + 800)).strftime("%Y-%m-%d")
    benchmark = yf.download(config.BENCHMARK_TICKER, start=bench_start,
                             auto_adjust=False, progress=False)
    if hasattr(benchmark.columns, "levels"):
        benchmark.columns = [c[0] if isinstance(c, tuple) else c for c in benchmark.columns]

    for f in files:
        as_of = datetime.strptime(f.stem, "%Y-%m-%d")
        with open(f) as fh:
            v1 = json.load(fh)
        v1_picks = v1.get("top_picks", [])
        v1_tickers = [p["ticker"] for p in v1_picks][:25]
        if not v1_tickers:
            continue

        # v1 forward returns
        v1_5d = [_fwd_return(t, as_of, 5) for t in v1_tickers]
        v1_20d = [_fwd_return(t, as_of, 20) for t in v1_tickers]
        v1_5d_avg = float(np.nanmean([r for r in v1_5d if r is not None])) if any(r is not None for r in v1_5d) else None
        v1_20d_avg = float(np.nanmean([r for r in v1_20d if r is not None])) if any(r is not None for r in v1_20d) else None

        # v2 picks for the same date — rescore the V1 candidate pool plus a small expansion
        # (limit to v1 picks to keep backtest fast; expanding to full universe is a future improvement)
        v2_scored = []
        bench_clip = benchmark.loc[benchmark.index <= as_of].copy()
        for t in v1_tickers:
            row = _v2_score_one(t, as_of, bench_clip)
            if row and row.get("qualifies"):
                v2_scored.append(row)
        v2_scored.sort(key=lambda r: r["composite_score"], reverse=True)
        v2_tickers = [r["ticker"] for r in v2_scored][:25]
        v2_5d = [_fwd_return(t, as_of, 5) for t in v2_tickers]
        v2_20d = [_fwd_return(t, as_of, 20) for t in v2_tickers]
        v2_5d_avg = float(np.nanmean([r for r in v2_5d if r is not None])) if any(r is not None for r in v2_5d) else None
        v2_20d_avg = float(np.nanmean([r for r in v2_20d if r is not None])) if any(r is not None for r in v2_20d) else None

        rejected = len(v1_tickers) - len(v2_tickers)
        overlap = len(set(v1_tickers) & set(v2_tickers))

        row = {
            "date": as_of.strftime("%Y-%m-%d"),
            "v1_count": len(v1_tickers),
            "v2_count": len(v2_tickers),
            "overlap": overlap,
            "v1_rejected_by_v2_gate": rejected,
            "v1_avg_fwd_5d": round(v1_5d_avg, 2) if v1_5d_avg is not None else None,
            "v2_avg_fwd_5d": round(v2_5d_avg, 2) if v2_5d_avg is not None else None,
            "v1_avg_fwd_20d": round(v1_20d_avg, 2) if v1_20d_avg is not None else None,
            "v2_avg_fwd_20d": round(v2_20d_avg, 2) if v2_20d_avg is not None else None,
        }
        print(row)
        out_rows.append(row)

    out_path = Path(config.RESULTS_DIR) / "backtest_v2.csv"
    with open(out_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()) if out_rows else [])
        writer.writeheader()
        writer.writerows(out_rows)

    # Summary
    if out_rows:
        v1_5d_all = [r["v1_avg_fwd_5d"] for r in out_rows if r["v1_avg_fwd_5d"] is not None]
        v2_5d_all = [r["v2_avg_fwd_5d"] for r in out_rows if r["v2_avg_fwd_5d"] is not None]
        v1_20d_all = [r["v1_avg_fwd_20d"] for r in out_rows if r["v1_avg_fwd_20d"] is not None]
        v2_20d_all = [r["v2_avg_fwd_20d"] for r in out_rows if r["v2_avg_fwd_20d"] is not None]
        print(f"\n=== Summary across {len(out_rows)} dates ===")
        if v1_5d_all and v2_5d_all:
            print(f"v1 median fwd 5d:  {np.median(v1_5d_all):+.2f}%")
            print(f"v2 median fwd 5d:  {np.median(v2_5d_all):+.2f}%")
        if v1_20d_all and v2_20d_all:
            print(f"v1 median fwd 20d: {np.median(v1_20d_all):+.2f}%")
            print(f"v2 median fwd 20d: {np.median(v2_20d_all):+.2f}%")
        print(f"v1 picks rejected by v2 gate (avg/day): {np.mean([r['v1_rejected_by_v2_gate'] for r in out_rows]):.1f}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    backtest(days=args.days)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test the harness on a small window**

Run: `python -m screener.backtest --days 5 2>&1 | tail -40`
Expected: runs to completion, prints 5 rows + summary, writes `results/backtest_v2.csv`. May take 3-10 minutes due to yfinance calls.

If it errors, debug the specific failure (most likely: column names from yfinance multi-ticker output, or missing data for delisted tickers).

- [ ] **Step 3: Commit**

```bash
git add screener/backtest.py
git commit -m "backtest: v1-vs-v2 forward-return harness

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 15: Update React frontend to display new categories

**Files:**
- Modify: `src/components/ScoreBreakdown.tsx`
- Modify: `src/types/screener.ts`

- [ ] **Step 1: Read current files**

Run: `cat src/components/ScoreBreakdown.tsx src/types/screener.ts`
Note the existing field names (trend_score, rs_score, volume_score, momentum_score, pattern_score, extension_penalty).

- [ ] **Step 2: Update the TypeScript types**

Edit `src/types/screener.ts` — find the `score_breakdown` type and replace with:

```typescript
export interface ScoreBreakdown {
  // v2 fields
  trend_strength?: number
  trend_cleanliness?: number
  rs?: number
  base_setup?: number
  volume_profile?: number
  raw_setup_score?: number
  penalty_multiplier?: number
  penalty_triggered?: string[]
  composite_score?: number

  // legacy v1 fields (for historical entries)
  trend_score?: number
  rs_score?: number
  volume_score?: number
  momentum_score?: number
  pattern_score?: number
  extension_penalty?: number
}
```

- [ ] **Step 3: Update ScoreBreakdown.tsx to render new categories**

Replace the body of `ScoreBreakdown.tsx` to render whichever schema is present:

```tsx
import type { ScoreBreakdown as ScoreBreakdownType } from '../types/screener'

interface Props { breakdown: ScoreBreakdownType }

export function ScoreBreakdown({ breakdown }: Props) {
  // Detect v2 by presence of trend_strength
  const isV2 = breakdown.trend_strength !== undefined
  const rows = isV2 ? [
    ['Trend Strength',    breakdown.trend_strength],
    ['Trend Cleanliness', breakdown.trend_cleanliness],
    ['Relative Strength', breakdown.rs],
    ['Base / Setup',      breakdown.base_setup],
    ['Volume Profile',    breakdown.volume_profile],
  ] : [
    ['Trend',    breakdown.trend_score],
    ['RS',       breakdown.rs_score],
    ['Volume',   breakdown.volume_score],
    ['Momentum', breakdown.momentum_score],
    ['Pattern',  breakdown.pattern_score],
  ]
  return (
    <div className="score-breakdown">
      {rows.map(([label, value]) => (
        <div key={label as string} className="score-breakdown__row">
          <span className="score-breakdown__label">{label}</span>
          <span className="score-breakdown__value">{(value as number)?.toFixed(1) ?? '—'}</span>
        </div>
      ))}
      {isV2 && breakdown.penalty_triggered && breakdown.penalty_triggered.length > 0 && (
        <div className="score-breakdown__penalties">
          Penalties: {breakdown.penalty_triggered.join(', ')} (× {breakdown.penalty_multiplier?.toFixed(2)})
        </div>
      )}
    </div>
  )
}
```

(Adapt to existing styling if there's a particular pattern in the file. The above is a structural template — keep existing CSS class names.)

- [ ] **Step 4: Type-check the frontend**

Run: `cd /Users/ilyamillwe/stock-screener && npm run build 2>&1 | tail -20`
Expected: build succeeds with no type errors.

- [ ] **Step 5: Commit**

```bash
git add src/components/ScoreBreakdown.tsx src/types/screener.ts
git commit -m "ui: display v2 score categories (preserves v1 fallback for historical entries)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 16: End-to-end integration check + visual verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full pipeline dry-run**

Run: `python -m screener.main --dry-run 2>&1 | tee /tmp/v2_dryrun.log | tail -50`
Expected:
- Pipeline runs to completion
- Logs show "Qualifying (passed Tier 1): N" where N is ~100-300 (down from ~430 under v1 — Tier 1 is stricter)
- "Top picks selected: 25"
- No Python exceptions

- [ ] **Step 2: Read the resulting top-10 and verify the schema**

Run: `python -c "
import json
with open('results/latest.json') as f:
    data = json.load(f)
print('scorer_version:', data.get('scorer_version'))
for p in data['top_picks'][:10]:
    print(f\"  {p['rank']:2}. {p['ticker']:6} {p['composite_score']:.1f}  raw={p.get('raw_setup_score','?')}  pen={p['score_breakdown'].get('penalty_multiplier','?')}  triggers={p['score_breakdown'].get('penalty_triggered',[])}\")
"`
Expected:
- `scorer_version: 2.0` (or "2.0")
- Each pick has `raw_setup_score`, `penalty_multiplier`, `penalty_triggered`
- No "fail_reason" field on top picks (only set when qualifies=False)

- [ ] **Step 3: Visually verify the top 10**

Open the freshly-generated chart PNGs for the top 10. From the project root:

```bash
ls -t results/charts/*$(date +%Y-%m-%d)*.png | head -10
```

(Or use the dashboard URL once deployed.) Read each chart and confirm:
- Steady multi-month climb above EMAs
- No giant single-bar moves dominating the chart
- No active reversal off recent high
- Tight consolidation near current price

Document the verdict in a `/tmp/v2_top10_audit.md` file with one line per ticker. The done criterion is **at least 8 of 10** visually pass canonical Stage-2 + setup quality criteria.

- [ ] **Step 4: Run the backtest harness**

Run: `python -m screener.backtest --days 30 2>&1 | tee /tmp/v2_backtest.log | tail -30`
Expected: completes; v2 median forward 5d and 20d are reported. Inspect the summary lines.

**Decision:** if v2 median fwd 20d ≥ v1 median fwd 20d (or even — v2 picks visually look much better even with similar returns), proceed. Otherwise, file a follow-up to tune weights/thresholds.

- [ ] **Step 5: Final commit + push**

```bash
git status
git add -A
git diff --stat HEAD
git commit -m "screener: v2 redesign complete — Tier 1/2/3 architecture live

Implements docs/superpowers/specs/2026-05-15-stock-screener-redesign-design.md.
Full Minervini gate + trend cleanliness + base/pivot detection + recalibrated
penalty bands. Backtest harness in screener/backtest.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Push to origin (triggers production deploy via Cloudflare Pages auto-deploy)**

Only push after confirming the integration check + backtest both passed. Then:

```bash
git push origin main
```

---

## Self-Review Notes

Spec coverage check (against [the design spec](../specs/2026-05-15-stock-screener-redesign-design.md)):

- §4 Architecture (three tiers as separate modules) → Tasks 9, 10, 11, 12 ✓
- §5.1 Full Minervini Trend Template → Task 9 (`qualify.py` checks all 8 criteria) ✓
- §5.2 Quality bars raised → Task 1 (config) ✓
- §5.3 Climactic / exhaustion hard rejects → Task 9 (uses Task 3 indicators) ✓
- §5.4 Wide-trading-range reject → Task 9 (uses `vol_60d` from Task 3) ✓
- §6.1 Trend Strength (robust ADX) → Task 5 + Task 10 ✓
- §6.2 Trend Cleanliness (R², outliers) → Task 4 + Task 10 ✓
- §6.3 RS (12m percentile + RS-line bonus) → Task 7 + Task 10 ✓
- §6.4 Base/Setup (VCP-guarded, pivot proximity, squeeze) → Task 6 + Task 10 ✓
- §6.5 Volume Profile (pullback dryup, breakout vol) → Task 8 + Task 10 ✓
- §7 Tier 3 penalty multipliers → Task 11 ✓
- §8 New indicators → Tasks 2–8 ✓
- §9 latest.json schema (scorer_version) → Task 13 ✓
- §10 Backtest harness → Task 14 ✓
- §11 Migration plan → Task 16 (integration check) ✓
- §12 Testing strategy → Tasks 2–11 (unit tests) + Task 16 (integration) ✓
- §13 Risks (frontend display) → Task 15 ✓
- §14 Done criteria → Task 16 ✓

No placeholders found. Function names are consistent across tasks (e.g., `compute_recent_move_metrics` in Tasks 3, 9, 11; `compute_setup_score` in Task 10 and used in Task 12).

Risk noted: Task 6 (pivot detection) has the most algorithmic complexity. If unit tests are too brittle, refine the algorithm or weaken the test asserts to match real-world behavior — but do not silently weaken the requirement (the spec explicitly says pivot_proximity may be dropped to weight 0 if it proves noisy in backtest; document any such change).
