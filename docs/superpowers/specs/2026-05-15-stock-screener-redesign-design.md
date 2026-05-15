# Stock Screener Redesign — Design Spec

Date: 2026-05-15
Status: Approved at Level 3 (architectural redesign)
Owner: ilyamiller14

## 1. Problem

The screener is producing top-25 lists dominated by charts that visually look bad: post-spike drifts, recent reversals, choppy non-trends, and one-bar rallies. An audit of the 2026-05-15 run found that only ~6–8 of the 25 picks are actually high-quality technical setups by canonical playbooks (Minervini Trend Template, O'Neil CANSLIM, IBD). The other ~17–19 fall into one of four failure modes:

1. **Spike pollution** — a single large gap or bar (e.g. SLAB's +49% earnings bar 69 sessions ago, MCW's +16% bar 60 sessions ago, BLBD's +17% gap 5 sessions ago) drives EMA alignment, ADX, and VCP scores even though the post-spike action is a flat shelf, not a trend.
2. **Active reversal** — the stock has just rolled over off its recent peak (OPLN -5% in 5d, NTCT -6% bar 2d ago, TGTX -4% today), but the screener only checks static distance from 52w high, not direction.
3. **Choppy non-trend** — EMAs are aligned but the underlying motion is sideways noise (WRBY R² = 0.01 with 8 big up bars and 9 big down bars; GVA R² = 0.06 where one day was 193% of the 60d return).
4. **Climactic / one-bar rally** — 35%+ of the 60-day rally came from a single day (DBRG 44%, MCW 74%, ALKS 87%, WRBY 87%).

The structural cause is two-fold:

- The **qualification gate** enforces only 4 of Minervini's 8 trend template criteria; with quality bars (`MIN_PRICE`, `MIN_AVG_VOLUME`) tuned permissively.
- The **composite score** mixes "is this stock in a healthy long-term uptrend?" with "is right now a good place to buy?". A stock can pass the first question (Stage 2 trend) without coming close to passing the second (a tradeable setup at a tradeable price).

The current penalty layer (`_extension_penalty_multiplier`) was designed for moonshot extension; it doesn't fire on normal spike/reversal/concentration cases.

## 2. Goals

- **Primary:** Top-10 picks should look like canonical Stage-2 advances with valid base/breakout setups — visually similar to GLNG (#1 today) or EBAY (#12 today).
- **Secondary:** Existing structure (Python pipeline → JSON → React dashboard + daily email) is preserved end-to-end. Only `screener/` internals change.
- **Tertiary:** A reproducible backtest harness so future scoring changes can be evaluated against historical runs.

## 3. Non-goals

- No change to the React frontend, email layout, GitHub Actions schedule, or `latest.json` schema beyond additive fields.
- No new fundamental data (earnings growth, sales, etc.) — this is a pure technicals redesign.
- No options data, no intraday data.
- No machine-learning model — interpretable rules-based scoring only.

## 4. Architecture — three explicit tiers

Today the pipeline is roughly `passes_hard_filters → compute_composite_score → _extension_penalty_multiplier`. Three concerns are tangled. Make them explicit and decoupled.

```
┌────────────────────────────┐    ┌────────────────────────────┐    ┌────────────────────────────┐
│   Tier 1                   │    │   Tier 2                   │    │   Tier 3                   │
│   Qualification Gate       │ →  │   Setup Quality Score      │ →  │   Penalty Multipliers      │
│   (reject if any fail)     │    │   (0-100, additive cats)   │    │   (multiplicative, ≤1.0)   │
└────────────────────────────┘    └────────────────────────────┘    └────────────────────────────┘
                                                                            │
                                                                            ▼
                                                              ┌──────────────────────────────┐
                                                              │  composite = score * Π(mult) │
                                                              │  → ranked top N              │
                                                              └──────────────────────────────┘
```

The current single-function composite is split into `qualify(ind)`, `score_setup(ind)`, `penalty_multiplier(ind)`. Each is independently testable. Module boundaries:

- `screener/qualify.py` — Tier 1 (returns `(passes: bool, fail_reason: str)`)
- `screener/setup_score.py` — Tier 2 (returns `{category_scores, total_score}`)
- `screener/penalties.py` — Tier 3 (returns `{multipliers: dict, final_multiplier: float, triggered: list[str]}`)
- `screener/scorer.py` — orchestrates the three tiers, keeps RS-percentile + sector cap
- `screener/indicators.py` — adds new indicators required by Tier 2/3
- `screener/backtest.py` — NEW; replays Tier 1–3 against historical OHLCV

## 5. Tier 1 — Qualification Gate (hard reject)

A stock must pass ALL of the following to reach scoring. Anything that fails is dropped — no graduated penalty.

### 5.1 Full Minervini Trend Template (8 criteria)

Currently the gate checks `close > EMA200` and `ema200_slope > 0`. Add the rest:

1. Close > EMA50
2. Close > EMA150
3. Close > EMA200  *(already enforced)*
4. EMA50 > EMA150
5. EMA150 > EMA200
6. EMA200 has been **rising for at least 22 sessions** (one trading month). New indicator: `ema200_rising_sessions` — the count of consecutive trailing sessions where today's EMA200 ≥ EMA200 from N-1 sessions ago. Require ≥ 22.
7. Close within 25% of 52w high  *(already enforced via `MAX_DIST_FROM_52W_HIGH_PCT`)*
8. Close ≥ 30% above 52w low. New requirement: `pct_above_52w_low ≥ 30`.

`ema_aligned` in current code already covers 1, 2, 3 + (close > EMA21). Use it as the base condition, then add 4, 5, 6, 8 explicitly.

### 5.2 Quality bars (raise)

- `MIN_PRICE`: 2 → **10**. Sub-$10 stocks are disproportionately spike-driven and have looser microstructure; this is consistent with canonical strategies.
- `MIN_AVG_VOLUME`: 100k → **300k**. Raises liquidity bar.
- `MIN_DOLLAR_VOLUME`: 20M → **25M**. Minor adjustment to align with new floors.
- `MIN_ADX`: 20 → **20** (no change — ADX is a soft signal in Tier 2 now).

### 5.3 Climactic / exhaustion rejects

Hard-reject if any of these are present in the lookback (180 sessions):

- `max_1d_move_pct ≥ 25.0` (close-to-close gain) — climactic single-bar
- `max_gap_pct ≥ 20.0` (overnight gap) — exhaustion gap

Lower thresholds (mild/moderate) live in Tier 3 as graduated penalties.

### 5.4 Wide-trading-range reject

If the close-to-close `vol_60` (stdev of daily returns over 60 sessions) > 8%, reject. Threshold sized to catch the obvious noise cases (a stock churning ±8%+ per day is not in a tradeable Stage-2 advance) while leaving healthy growth names alone (typical 1–4% daily stdev). WRBY today is at 5.7% — it would NOT be rejected by this rule, but it WILL be caught in Tier 2 by `r2_log_60d = 0.01` (which maps to a near-zero cleanliness score).

## 6. Tier 2 — Setup Quality Score (0-100)

Five categories. Weights chosen to emphasize what canonical playbooks emphasize: trend strength + RS dominate, setup quality matters, volume matters in context.

**Note on the dropped "momentum" category:** Today's scorer has a 15% Momentum category driven by RSI, MACD-histogram, and MACD-crossover recency. v2 drops this category. Minervini's SEPA, O'Neil's CANSLIM, and IBD's RS Rating do not use RSI or MACD as core scoring inputs — they use price action vs. moving averages, RS, base patterns, and volume. The momentum signal that *does* appear in those playbooks (trend strength via ADX) lives in Trend Strength §6.1. RSI and MACD-hist are still computed in `indicators.py` (existing code unchanged) but are no longer fed to the composite score — they remain available for display in the dashboard if useful.

| Category | Weight | What it measures |
|---|---|---|
| A. Trend Strength | 0.25 | EMA spread / slope / ADX (robust) |
| B. Trend Cleanliness | 0.15 | R² of log-price regression + outlier-bar count |
| C. Relative Strength | 0.25 | IBD-style RS + 3/6/12m, bonus for RS-line at new highs |
| D. Base / Setup Quality | 0.20 | VCP (guarded), Squeeze, proximity to pivot |
| E. Volume Profile | 0.15 | OBV slope, CMF, up-day vol ratio, breakout-day vol |

### 6.1 A — Trend Strength (25%)

Sub-weights (within category):

- `ema_alignment`: 0.20 — binary, 100 if `ema_aligned` else 0. *(reduced from 0.30 today)*
- `ema200_slope_sustained`: 0.30 — graduated. Score = clamp(`ema200_slope * 200`, 0, 100) **AND** require it to have been positive for `ema200_rising_sessions` ≥ 22 (already enforced in gate, but this ensures a sustained positive slope gets credit).
- `ema50_above_ema200_pct`: 0.20 — graduated. Score = clamp((`ema50/ema200 - 1`) * 500, 0, 100). Rewards larger spread (healthier trend).
- `dist_from_52w_high`: 0.10 — graduated. *(reduced from 0.25 today)*
- `adx_robust`: 0.20 — graduated. **Robust ADX:** drop the top 2 True-Range bars in the 14-bar window before computing TR sums. This kills the SLAB problem (ADX 54 from one bar). Score = clamp(`adx_robust * 2.0`, 0, 100).

### 6.2 B — Trend Cleanliness (15%) — NEW

Sub-weights:

- `r2_log_60d`: 0.60 — R² of OLS regression of `log(close)` on session index over last 60 sessions. Score = clamp((`r2 - 0.40`) * 200, 0, 100). R² < 0.40 → 0; R² ≥ 0.90 → 100. Kills WRBY (0.01), MCW (0.08), GVA (0.06).
- `outlier_bar_ratio`: 0.40 — count of bars in last 60 sessions where `|daily_return| > 4σ` of the 60-day return distribution. Score = clamp(100 - count * 25, 0, 100). 0 outliers → 100; 4+ outliers → 0.

### 6.3 C — Relative Strength (25%)

Same inputs but re-weighted to bias toward IBD-style (best historical predictor per IBD 1950–2008 data showing 87 avg RS rating for winners):

- `ibd_rs_percentile`: 0.65 *(up from 0.50)*
- `rs_3m_percentile`: 0.20
- `rs_6m_percentile`: 0.10
- `rs_12m_percentile`: 0.05 — new (12-month RS, percentile-ranked within qualifying universe).

Bonus: if the **RS line** is at a 50-session high, add a flat +10 to the category score (capped at 100). RS line is defined as `ticker_close / spy_close` rebased so `rs_line[0] = 1.0`. "At a 50-session high" means `rs_line[-1] ≥ max(rs_line[-50:])`. This is the "RS new-high" leadership signal IBD emphasizes — when a stock is outperforming SPY at a fresh high even before its own price breaks out, it's a leadership tell.

### 6.4 D — Base / Setup Quality (20%)

Replaces today's `pattern_score`. Three sub-components:

- `vcp_guarded`: 0.40 — VCP score, but **skip detection entirely** (returns 0) if any bar within the 120-day lookback had `|daily_return| > 12%` OR `|gap| > 10%`. This forces the algorithm to only grade clean bases. Kills SLAB-style fake VCPs.
- `pivot_proximity`: 0.30 — NEW. Identify the most recent consolidation in the last 50 sessions:
  1. Find 5-bar swing highs and swing lows in the last 60 sessions (same pivot logic already used in `compute_vcp` and `compute_support_resistance`).
  2. Walk backward from the most recent bar and find the latest contiguous cluster of swings where `(max_high - min_low) / max_high ≤ 0.15` (i.e. range ≤ 15%) and the cluster spans ≥ 15 trading days (3 weeks) and ≤ 40 trading days (8 weeks).
  3. The **pivot** is `max_high` of that cluster. `base_depth_pct = (max_high - min_low) / max_high * 100`. `base_length_days = end_idx - start_idx`.
  4. `dist_from_pivot_pct = (last_close - pivot) / pivot * 100` (positive = above pivot, negative = below).
  5. If no cluster satisfies the rules, all fields default (`pivot=0`, `dist_from_pivot_pct=99`) and sub-score = 0.

  Sub-score = clamp(100 - |dist_from_pivot_pct - 0.5| * 20, 0, 100). Slightly above pivot (0.5%) → 100; ≥5% above → 0 (extended past breakout); 5% below → 0 (not yet at buy point). This rewards stocks *at* the pivot, which is the canonical O'Neil/Minervini buy point.
- `squeeze_score`: 0.30 — existing squeeze logic, no changes.

### 6.5 E — Volume Profile (15%)

Restructure slightly. Today's `volume_ratio` is "today's vol / 20d avg" which conflates "breakout day" with "any random day." Replace with two specific signals:

- `obv_slope`: 0.20 — existing.
- `cmf_20`: 0.25 — existing.
- `pullback_volume_dryup`: 0.25 — NEW. During the last 10-day pullback (defined as the most recent consecutive down-day cluster of 3+ days), the average volume should be **lower** than the 20-day average. Compute `pullback_vol_ratio = avg(volume during pullback) / avg_volume_20d`. Score = clamp((1.0 - `pullback_vol_ratio`) * 200, 0, 100). Volume dry-up on pullback (ratio 0.5) → 100; volume surge on pullback (ratio 1.5) → 0.
- `breakout_day_volume`: 0.30 — NEW. If today's price is within 2% of a pivot (from D.pivot_proximity), today's volume must be ≥ 1.5× the 20-day average. Score = clamp((`volume_ratio` - 1.0) * 50, 0, 100). Only contributes when at/near a pivot; otherwise neutral (score = 50). Captures the O'Neil "breakout on 1.5×+ avg volume" rule.

## 7. Tier 3 — Penalty Multipliers

Multiplicative on the Tier 2 score. Each is independently triggered; the final multiplier is the **minimum** of all triggered multipliers (floor 0.05), as today.

| Penalty | Trigger | Multiplier |
|---|---|---|
| Climactic single bar (mild) | `max_1d_move_120d` ≥ 10% | 0.85 |
| Climactic single bar (heavy) | `max_1d_move_120d` ≥ 15% | 0.50 |
| Climactic single bar (severe) | `max_1d_move_120d` ≥ 20% | 0.25 |
| Exhaustion gap (mild) | `max_gap_120d` ≥ 10% | 0.80 |
| Exhaustion gap (heavy) | `max_gap_120d` ≥ 15% | 0.40 |
| Rally concentration | `concentration_60d` ≥ 35% | 0.60 |
| Rally concentration (severe) | `concentration_60d` ≥ 60% | 0.30 |
| Recent reversal (mild) | `dist_from_5d_high_pct` ≥ 3% | 0.70 |
| Recent reversal (heavy) | `dist_from_5d_high_pct` ≥ 7% | 0.40 |
| 52w-low extension (recalibrated) | `pct_above_52w_low` ≥ 60% | 0.85 |
| 52w-low extension (heavy) | `pct_above_52w_low` ≥ 120% | 0.60 |
| 52w-low extension (severe) | `pct_above_52w_low` ≥ 250% | 0.30 |
| ATR extension | existing ATR-based — unchanged | 0.85 / 0.50 / 0.10 |

`concentration_60d` formula: `max_single_day_gain_60d / total_60d_return * 100` if total return > 0, else 0.

`dist_from_5d_high_pct` formula: `(max(High[-5:]) - last_close) / max(High[-5:]) * 100`.

Floor: final multiplier never below 0.05 (matches current behavior).

## 8. New / changed indicators in `indicators.py`

Add the following helpers (return values in flat indicator dict):

- `ema200_rising_sessions` (int) — for Tier 1 §5.1.
- `max_1d_move_120d` (float, %) — for Tier 1 §5.3 + Tier 3.
- `max_gap_120d` (float, %) — replaces today's 20-day `max_gap_pct`. Update `GAP_LOOKBACK_DAYS: 20 → 120`.
- `concentration_60d` (float, %) — for Tier 3.
- `dist_from_5d_high_pct`, `dist_from_10d_high_pct`, `dist_from_20d_high_pct` (float, %) — for Tier 3.
- `r2_log_60d` (float, 0–1) — for Tier 2 §6.2.
- `outlier_bar_count_60d` (int) — for Tier 2 §6.2.
- `vol_60d` (float, %) — for Tier 1 §5.4.
- `adx_robust` (float) — new robust ADX function in `compute_adx`. Returns both `adx_14` (existing) and `adx_robust` (new).
- `pullback_vol_ratio` (float) — for Tier 2 §6.5.
- `pivot_price`, `pivot_date_idx`, `dist_from_pivot_pct`, `base_depth_pct`, `base_length_days` — for Tier 2 §6.4 (`pivot_proximity` sub-score).
- `rs_12m_percentile` (computed in scorer.py alongside 3m/6m percentiles) — for Tier 2 §6.3.
- `rs_line_at_50d_high` (bool) — for Tier 2 §6.3 bonus.

All new indicators emit defaults (0 / False) if data is insufficient. Existing indicators keep their names.

## 9. Output schema additions in `latest.json`

The `top_picks[i]` schema gains:

```json
{
  "rank": ...,
  "ticker": ...,
  ...existing fields...,
  "score_breakdown": {
    "trend_strength":    <0-100>,
    "trend_cleanliness": <0-100>,    // NEW
    "rs":                <0-100>,
    "base_setup":        <0-100>,    // RENAMED from pattern
    "volume_profile":    <0-100>,    // RENAMED from volume
    "raw_setup_score":   <0-100>,    // pre-penalty
    "penalty_triggered": ["climactic_severe","reversal_mild"],   // NEW
    "penalty_multiplier": <0.05-1.0>,
    "composite_score":   <0-100>     // raw_setup_score * penalty_multiplier
  },
  "indicators": { ...all new fields included for transparency... }
}
```

`composite_score` at the top level is preserved (existing dashboard reads it). Frontend continues to work unchanged; ScoreBreakdown.tsx may optionally be updated to display the new categories.

`run_meta` field at top level grows to include scorer version so historical runs can be told apart:

```json
"scorer_version": "2.0",
"scorer_revised_at": "2026-05-15"
```

## 10. Backtest harness (`screener/backtest.py`)

Goal: replay the new scorer against historical OHLCV so we can quantitatively compare v1 (current) vs v2 (this redesign) before rolling out.

Inputs:
- Date range (default: last 30 trading days)
- Ticker universe (reuse `tickers.json`)

For each `as_of_date` in range:
1. Fetch OHLCV through `as_of_date` (yfinance, 2y window — same as live).
2. Run Tier 1 → 2 → 3 to produce v2 top 25.
3. Pull v1 top 25 from `results/history/<date>.json`.
4. Compute forward returns for both lists at 5d, 10d, 20d (using actual price data after `as_of_date`).
5. Emit a comparison row: `date | v1_overlap_with_v2 | v1_avg_fwd_5d | v2_avg_fwd_5d | v1_avg_fwd_20d | v2_avg_fwd_20d | n_v1_rejected_by_v2_gate`.

Output: `results/backtest_v2.csv` + summary printed to stdout.

This is the empirical answer to "did the redesign actually pick better stocks?". A v2 that doesn't beat v1 on forward returns is a v2 that doesn't ship.

## 11. Migration plan

Pure additive replacement (no flag, no shadowing — the next daily run uses v2):

1. Add new indicators to `indicators.py`.
2. Implement `qualify.py`, `setup_score.py`, `penalties.py`.
3. Rewire `scorer.py` to call the three modules in sequence.
4. Update `config.py` thresholds (MIN_PRICE, MIN_AVG_VOLUME, gap lookback, new penalty bands).
5. Add `backtest.py` and run against last 30 days.
6. If backtest shows neutral-or-better forward returns AND visual top-10 looks like canonical setups (verified by reading a sample of chart PNGs), commit and deploy. Otherwise iterate before deploy.
7. Update `screener/main.py` to embed `scorer_version` in JSON output.
8. Update `src/components/ScoreBreakdown.tsx` to display new category names (small UI change).

No DB. No migrations. Old `latest.json` is overwritten by the next daily run. Old history files remain as-is — they'll just have the v1 schema and we won't regenerate them.

## 12. Testing strategy

Unit tests in `tests/` (existing pytest harness):

- `tests/test_qualify.py` — each gate criterion in isolation. Fixtures: synthetic OHLCV for each pass/fail case.
- `tests/test_setup_score.py` — each category and sub-component computes expected values for fixed inputs.
- `tests/test_penalties.py` — each penalty triggers at the right thresholds and the minimum-multiplier composition works.
- `tests/test_indicators_new.py` — new indicators (R², concentration, pivot detection, robust ADX) against hand-computed expected values on small synthetic DataFrames.
- `tests/test_scorer_v2.py` — end-to-end: feed mock OHLCV for SLAB (post-spike), GLNG (clean trend), WRBY (chop) and assert v2 ranks GLNG > SLAB > WRBY (today v1 reverses this).

Integration check: `python -m screener.main --dry-run` succeeds end-to-end on the live universe with no exceptions and produces a valid `latest.json`.

Backtest check (gating before deploy): run `python -m screener.backtest --days 30` and confirm:
- v2 forward 5-day return ≥ v1 forward 5-day return (median across the 30 runs), OR
- v2 picks visually pass quality bar on at least 8/10 of a randomly sampled top-10 from any one run, even if forward returns are neutral.

## 13. Risks and trade-offs

- **Tightening the gate could shrink the qualifying universe.** Currently ~430 of ~2300 qualify. Estimate after Level 3 gate: ~150–250. Top-25 may sometimes have <25 entries on weak market days. Acceptable — the dashboard already handles variable counts.
- **`pivot_proximity` is the hardest to implement** and the most likely to need iteration. Risk mitigation: ship pivot_proximity with weight 0.30 in Base/Setup category, but if backtest shows the metric is noisy, drop weight to 0 and let `vcp_guarded` + `squeeze_score` carry the category until v2.1.
- **Trend cleanliness (R²) penalizes news-driven gappers that look choppy** even when the trend is real. Mitigation: R² is only 15% of total score, and outlier-bar count gives a check on this.
- **Backtest validity:** yfinance historical bars sometimes diverge from real-time prices on the original `as_of_date`. Mitigation: backtest is a sanity check, not a backtest in the academic sense — directional signal is what matters.
- **Frontend display:** old `score_breakdown` keys (`pattern_score`, `volume_score`) disappear. Mitigation: update ScoreBreakdown.tsx to handle both old and new key names defensively, so historical entries don't break the UI.

## 14. Done criteria

- All unit tests pass.
- `python -m screener.main --dry-run` produces a top-25 where 8+ of the top 10 picks visually pass canonical Stage-2 + setup quality criteria (verified by reading chart PNGs).
- `python -m screener.backtest --days 30` runs to completion and produces a CSV with v1 vs v2 comparison.
- Deployed to production via the existing GitHub Action; next daily run uses v2.
