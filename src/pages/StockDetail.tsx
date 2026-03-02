import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ScoreBreakdown } from '../components/ScoreBreakdown'
import { useScreenerData } from '../hooks/useScreenerData'
import './StockDetail.css'

export default function StockDetail() {
  const { ticker } = useParams<{ ticker: string }>()
  const navigate = useNavigate()
  const { data, isLoading, error, noData, refetch } = useScreenerData()
  const [chartFailed, setChartFailed] = useState(false)

  if (isLoading) {
    return <div className="detail-loading"><div className="spinner" /> Loading…</div>
  }
  if (error) {
    return (
      <div className="detail-error">
        <p>{error}</p>
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={refetch} className="btn btn--primary">Retry</button>
          <button onClick={() => navigate('/')} className="btn btn--primary">Back to Dashboard</button>
        </div>
      </div>
    )
  }
  if (noData || !data) {
    return (
      <div className="detail-error">
        <p>No screening results available yet.</p>
        <button onClick={() => navigate('/')} className="btn btn--primary">Back to Dashboard</button>
      </div>
    )
  }

  const pick = data.top_picks.find((p) => p.ticker === ticker)
  if (!pick) {
    return (
      <div className="detail-error">
        <p>Ticker {ticker} not found in today's top picks.</p>
        <button onClick={() => navigate('/')} className="btn btn--primary">Back to Dashboard</button>
      </div>
    )
  }

  const { indicators, score_breakdown } = pick
  const changeColor = pick.change_pct >= 0 ? '#26a641' : '#da3633'
  const changeArrow = pick.change_pct >= 0 ? '▲' : '▼'

  function scoreColor(score: number): string {
    if (score >= 75) return '#26a641'
    if (score >= 60) return '#e3b341'
    return '#6e7681'
  }

  const dist = pick.dist_from_52w_high_pct
  const distLabel = dist <= 0 ? 'At high' : `${dist.toFixed(1)}% below`

  function capitalize(s: string): string {
    return s.charAt(0).toUpperCase() + s.slice(1)
  }

  return (
    <div className="detail">
      <button className="detail__back" onClick={() => navigate('/')}>← Dashboard</button>

      <div className="detail__header">
        <div className="detail__title-block">
          <div>
            <span className="detail__ticker">{pick.ticker}</span>
            {pick.stage2 && <span className="badge badge--stage2" style={{ marginLeft: 10 }}>Stage 2</span>}
          </div>
          <div className="detail__company">{pick.company_name}</div>
          <div className="detail__sector">{pick.sector} · {pick.industry}</div>
        </div>
        <div className="detail__price-block">
          <div className="detail__price">${pick.close.toFixed(2)}</div>
          <div style={{ color: changeColor, fontSize: 14 }}>
            {changeArrow} {Math.abs(pick.change_pct).toFixed(2)}%
          </div>
          <div style={{ fontSize: 28, fontWeight: 700, color: scoreColor(pick.composite_score), marginTop: 4 }}>
            {pick.composite_score.toFixed(1)}<span style={{ fontSize: 12, color: '#6e7681' }}>/100</span>
          </div>
        </div>
      </div>

      {/* Chart */}
      {!chartFailed ? (
        <div className="detail__chart">
          <img
            src={pick.chart_url}
            alt={`${pick.ticker} technical chart`}
            className="detail__chart-img"
            onError={() => setChartFailed(true)}
          />
        </div>
      ) : (
        <div className="detail__chart" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#6e7681', fontSize: 13 }}>
          Chart not available
        </div>
      )}

      {/* Score breakdown */}
      <div className="detail__section">
        <ScoreBreakdown breakdown={score_breakdown} />
      </div>

      {/* Indicator table */}
      <div className="detail__section">
        <div className="detail__section-title">Technical Indicators</div>
        <div className="indicator-grid">
          <div className="ind-group">
            <div className="ind-group__title">Trend</div>
            <div className="ind-row"><span>EMA 21</span><span>${indicators.ema_21.toFixed(2)}</span></div>
            <div className="ind-row"><span>EMA 50</span><span>${indicators.ema_50.toFixed(2)}</span></div>
            <div className="ind-row"><span>EMA 150</span><span>${indicators.ema_150.toFixed(2)}</span></div>
            <div className="ind-row"><span>EMA 200</span><span>${indicators.ema_200.toFixed(2)}</span></div>
            <div className="ind-row"><span>EMA Aligned</span><span style={{ color: indicators.ema_aligned ? '#26a641' : '#da3633' }}>{indicators.ema_aligned ? 'Yes' : 'No'}</span></div>
            <div className="ind-row"><span>EMA 200 Slope</span><span>{indicators.ema_200_slope_pct.toFixed(4)}%/d</span></div>
            <div className="ind-row"><span>ADX (14)</span><span style={{ color: indicators.adx_14 > 25 ? '#26a641' : '#c9d1d9' }}>{indicators.adx_14.toFixed(1)}</span></div>
            <div className="ind-row"><span>ADX Trending</span><span style={{ color: indicators.adx_trending ? '#26a641' : '#6e7681' }}>{indicators.adx_trending ? 'Yes' : 'No'}</span></div>
          </div>

          <div className="ind-group">
            <div className="ind-group__title">Momentum</div>
            <div className="ind-row"><span>RSI (14)</span><span style={{ color: indicators.rsi_14 > 70 ? '#da3633' : indicators.rsi_14 < 30 ? '#58a6ff' : '#c9d1d9' }}>{indicators.rsi_14.toFixed(1)}</span></div>
            <div className="ind-row"><span>MACD</span><span>{indicators.macd.toFixed(4)}</span></div>
            <div className="ind-row"><span>MACD Signal</span><span>{indicators.macd_signal.toFixed(4)}</span></div>
            <div className="ind-row"><span>MACD Hist</span><span style={{ color: indicators.macd_hist >= 0 ? '#26a641' : '#da3633' }}>{indicators.macd_hist >= 0 ? '+' : ''}{indicators.macd_hist.toFixed(4)}</span></div>
            <div className="ind-row"><span>MACD Crossover</span><span style={{ color: indicators.macd_crossover_bullish ? '#26a641' : '#6e7681' }}>{indicators.macd_crossover_bullish ? 'Bullish' : 'No'}</span></div>
          </div>

          <div className="ind-group">
            <div className="ind-group__title">Volume / Accum</div>
            <div className="ind-row"><span>OBV Trend</span><span style={{ color: indicators.obv_trend === 'rising' ? '#26a641' : indicators.obv_trend === 'falling' ? '#da3633' : '#8b949e' }}>{capitalize(indicators.obv_trend)}</span></div>
            <div className="ind-row"><span>CMF (20)</span><span style={{ color: indicators.cmf_20 >= 0 ? '#26a641' : '#da3633' }}>{indicators.cmf_20 >= 0 ? '+' : ''}{indicators.cmf_20.toFixed(2)}</span></div>
            <div className="ind-row"><span>Volume Ratio</span><span>{indicators.volume_ratio.toFixed(2)}x</span></div>
          </div>

          <div className="ind-group">
            <div className="ind-group__title">Relative Strength</div>
            <div className="ind-row"><span>IBD RS Percentile</span><span style={{ color: indicators.ibd_rs_percentile >= 80 ? '#26a641' : '#c9d1d9', fontWeight: 700 }}>{indicators.ibd_rs_percentile.toFixed(0)}</span></div>
            <div className="ind-row"><span>RS 3M Percentile</span><span style={{ color: indicators.rs_3m_percentile >= 80 ? '#26a641' : '#c9d1d9' }}>{indicators.rs_3m_percentile.toFixed(0)}</span></div>
            <div className="ind-row"><span>RS 6M Percentile</span><span style={{ color: indicators.rs_6m_percentile >= 80 ? '#26a641' : '#c9d1d9' }}>{indicators.rs_6m_percentile.toFixed(0)}</span></div>
          </div>

          <div className="ind-group">
            <div className="ind-group__title">Pattern (VCP / Squeeze)</div>
            <div className="ind-row"><span>VCP Detected</span><span style={{ color: indicators.vcp_detected ? '#58a6ff' : '#6e7681', fontWeight: indicators.vcp_detected ? 700 : 400 }}>{indicators.vcp_detected ? 'Yes' : 'No'}</span></div>
            <div className="ind-row"><span>VCP Score</span><span>{indicators.vcp_score.toFixed(0)}</span></div>
            <div className="ind-row"><span>Contractions</span><span>{indicators.vcp_contractions}</span></div>
            <div className="ind-row"><span>Tightness</span><span>{indicators.vcp_tightness.toFixed(2)}x</span></div>
            <div className="ind-row"><span>Squeeze</span><span style={{ color: indicators.squeeze_fired ? '#f0883e' : indicators.squeeze_on ? '#e3b341' : '#6e7681', fontWeight: indicators.squeeze_fired ? 700 : 400 }}>{indicators.squeeze_fired ? 'Fired' : indicators.squeeze_on ? `On (${indicators.squeeze_bars} bars)` : 'Off'}</span></div>
            <div className="ind-row"><span>Squeeze Score</span><span>{indicators.squeeze_score.toFixed(0)}</span></div>
          </div>

          <div className="ind-group">
            <div className="ind-group__title">52-Week</div>
            <div className="ind-row"><span>52W High</span><span>${pick.high_52w.toFixed(2)}</span></div>
            <div className="ind-row"><span>52W Low</span><span>${pick.low_52w.toFixed(2)}</span></div>
            <div className="ind-row"><span>vs 52W High</span><span style={{ color: dist < 10 ? '#26a641' : '#c9d1d9' }}>{distLabel}</span></div>
          </div>
        </div>
      </div>

      <div className="detail__footer">
        <a
          href={`https://finance.yahoo.com/chart/${pick.ticker}`}
          target="_blank"
          rel="noopener noreferrer"
          className="detail__ext-link"
        >
          Open in Yahoo Finance →
        </a>
        <a
          href={`https://www.tradingview.com/chart/?symbol=${pick.ticker}`}
          target="_blank"
          rel="noopener noreferrer"
          className="detail__ext-link"
        >
          Open in TradingView →
        </a>
      </div>
    </div>
  )
}
