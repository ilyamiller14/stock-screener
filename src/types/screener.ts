export interface ScoreBreakdown {
  trend_score: number
  rs_score: number
  volume_score: number
  momentum_score: number
  stage2_score: number
}

export interface Indicators {
  ema_21: number
  ema_50: number
  ema_150: number
  ema_200: number
  ema_aligned: boolean
  ema_200_slope_pct: number
  rsi_14: number
  macd: number
  macd_signal: number
  macd_hist: number
  macd_crossover_bullish: boolean
  adx_14: number
  adx_trending: boolean
  obv_trend: 'rising' | 'flat' | 'falling'
  cmf_20: number
  rs_3m_percentile: number
  rs_6m_percentile: number
  volume_ratio: number
}

export interface TopPick {
  rank: number
  ticker: string
  company_name: string
  sector: string
  industry: string
  close: number
  change_pct: number
  volume: number
  avg_volume_20d: number
  high_52w: number
  low_52w: number
  dist_from_52w_high_pct: number
  composite_score: number
  score_breakdown: ScoreBreakdown
  indicators: Indicators
  stage2: boolean
  chart_url: string
}

export interface ScreenerResults {
  run_date: string
  run_timestamp: string
  screened_count: number
  qualifying_count: number
  top_picks: TopPick[]
}

export type SortKey =
  | 'composite_score'
  | 'rs_score'
  | 'trend_score'
  | 'adx_14'
  | 'rsi_14'
  | 'cmf_20'
  | 'rs_3m_percentile'
  | 'dist_from_52w_high_pct'
