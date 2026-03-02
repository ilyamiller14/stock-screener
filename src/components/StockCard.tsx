import { useNavigate } from 'react-router-dom'
import type { TopPick } from '../types/screener'
import './StockCard.css'

interface Props {
  pick: TopPick
}

function ScoreBar({ score, color }: { score: number; color: string }) {
  return (
    <div className="score-bar">
      <div className="score-bar__fill" style={{ width: `${score}%`, background: color }} />
    </div>
  )
}

function scoreColor(score: number): string {
  if (score >= 75) return '#26a641'
  if (score >= 60) return '#e3b341'
  return '#6e7681'
}

export function StockCard({ pick }: Props) {
  const navigate = useNavigate()
  const {
    rank, ticker, company_name, sector, close, change_pct,
    composite_score, score_breakdown, indicators, stage2, vcp, squeeze,
    dist_from_52w_high_pct,
  } = pick

  const changeColor  = change_pct >= 0 ? '#26a641' : '#da3633'
  const changeArrow  = change_pct >= 0 ? '▲' : '▼'

  return (
    <div className="stock-card" onClick={() => navigate(`/stock/${ticker}`)}>
      <div className="stock-card__header">
        <div className="stock-card__left">
          <span className="stock-card__rank">#{rank}</span>
          <span className="stock-card__ticker">{ticker}</span>
          {stage2 && <span className="badge badge--stage2">S2</span>}
          {vcp && <span className="badge badge--vcp">VCP</span>}
          {indicators.squeeze_fired && <span className="badge badge--squeeze-fire">Squeeze Fire</span>}
          {!indicators.squeeze_fired && squeeze && <span className="badge badge--squeeze">Squeeze</span>}
          <div className="stock-card__company">{company_name}</div>
          <div className="stock-card__sector">{sector}</div>
        </div>
        <div className="stock-card__right">
          <div className="stock-card__price">${close.toFixed(2)}</div>
          <div className="stock-card__change" style={{ color: changeColor }}>
            {changeArrow} {Math.abs(change_pct).toFixed(2)}%
          </div>
          <div className="stock-card__score" style={{ color: scoreColor(composite_score) }}>
            {composite_score.toFixed(1)}
            <span className="stock-card__score-denom">/100</span>
          </div>
        </div>
      </div>

      <div className="stock-card__bars">
        <ScoreBar score={score_breakdown.trend_score}    color="#238636" />
        <ScoreBar score={score_breakdown.rs_score}       color="#58a6ff" />
        <ScoreBar score={score_breakdown.volume_score}   color="#bc8cff" />
        <ScoreBar score={score_breakdown.momentum_score} color="#e3b341" />
        <ScoreBar score={score_breakdown.pattern_score}  color="#f0883e" />
      </div>

      <div className="stock-card__metrics">
        <div className="metric">
          <div className="metric__label">IBD RS</div>
          <div className="metric__value">{indicators.ibd_rs_percentile.toFixed(0)}</div>
        </div>
        <div className="metric">
          <div className="metric__label">ADX</div>
          <div className="metric__value">{indicators.adx_14.toFixed(1)}</div>
        </div>
        <div className="metric">
          <div className="metric__label">RSI 14</div>
          <div className="metric__value">{indicators.rsi_14.toFixed(1)}</div>
        </div>
        <div className="metric">
          <div className="metric__label">CMF</div>
          <div className="metric__value">{indicators.cmf_20 >= 0 ? '+' : ''}{indicators.cmf_20.toFixed(2)}</div>
        </div>
        <div className="metric">
          <div className="metric__label">OBV</div>
          <div className="metric__value">{indicators.obv_trend}</div>
        </div>
        <div className="metric">
          <div className="metric__label">vs 52W Hi</div>
          <div className="metric__value">{dist_from_52w_high_pct.toFixed(1)}%</div>
        </div>
      </div>
    </div>
  )
}
