import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { SortKey, TopPick } from '../types/screener'
import './StockTable.css'

interface Props {
  picks: TopPick[]
}

function scoreColor(score: number): string {
  if (score >= 75) return '#26a641'
  if (score >= 60) return '#e3b341'
  return '#6e7681'
}

const COLUMNS: { key: SortKey | 'ticker' | 'sector'; label: string; align?: 'right' }[] = [
  { key: 'ticker',            label: 'Ticker' },
  { key: 'sector',            label: 'Sector' },
  { key: 'composite_score',   label: 'Score',    align: 'right' },
  { key: 'ibd_rs_percentile', label: 'IBD RS',   align: 'right' },
  { key: 'trend_score',       label: 'Trend',    align: 'right' },
  { key: 'pattern_score',     label: 'Pattern',  align: 'right' },
  { key: 'adx_14',            label: 'ADX',      align: 'right' },
  { key: 'rsi_14',            label: 'RSI',      align: 'right' },
  { key: 'cmf_20',            label: 'CMF',      align: 'right' },
]

function getValue(pick: TopPick, key: string): number | string {
  if (key === 'ticker')  return pick.ticker
  if (key === 'sector')  return pick.sector
  if (key === 'composite_score') return pick.composite_score
  if (key === 'trend_score')     return pick.score_breakdown.trend_score
  if (key === 'rs_score')        return pick.score_breakdown.rs_score
  if (key === 'pattern_score')   return pick.score_breakdown.pattern_score
  if (key === 'ibd_rs_percentile') return pick.indicators.ibd_rs_percentile
  if (key === 'adx_14')          return pick.indicators.adx_14
  if (key === 'rsi_14')          return pick.indicators.rsi_14
  if (key === 'cmf_20')          return pick.indicators.cmf_20
  if (key === 'dist_from_52w_high_pct') return pick.dist_from_52w_high_pct
  return 0
}

export function StockTable({ picks }: Props) {
  const navigate = useNavigate()
  const [sortKey, setSortKey] = useState<string>('composite_score')
  const [sortAsc, setSortAsc] = useState(false)

  const sorted = [...picks].sort((a, b) => {
    const av = getValue(a, sortKey)
    const bv = getValue(b, sortKey)
    if (typeof av === 'string' && typeof bv === 'string') {
      return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av)
    }
    return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number)
  })

  function handleSort(key: string) {
    if (key === sortKey) {
      setSortAsc((a) => !a)
    } else {
      setSortKey(key)
      setSortAsc(false)
    }
  }

  return (
    <div className="stock-table-wrapper">
      <table className="stock-table">
        <thead>
          <tr>
            <th className="stock-table__th stock-table__th--rank">#</th>
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                className={`stock-table__th ${col.align === 'right' ? 'stock-table__th--right' : ''} ${sortKey === col.key ? 'stock-table__th--active' : ''}`}
                onClick={() => handleSort(col.key)}
              >
                {col.label}
                {sortKey === col.key && (
                  <span className="sort-icon">{sortAsc ? ' ↑' : ' ↓'}</span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((pick) => (
            <tr
              key={pick.ticker}
              className="stock-table__row"
              onClick={() => navigate(`/stock/${pick.ticker}`)}
            >
              <td className="stock-table__td stock-table__td--rank">{pick.rank}</td>
              <td className="stock-table__td">
                <span className="stock-table__ticker">{pick.ticker}</span>
                {pick.stage2 && <span className="badge badge--stage2 badge--sm">S2</span>}
                {pick.vcp && <span className="badge badge--vcp badge--sm">VCP</span>}
                {pick.squeeze && <span className="badge badge--squeeze badge--sm">SQ</span>}
              </td>
              <td className="stock-table__td stock-table__td--muted">{pick.sector}</td>
              <td className="stock-table__td stock-table__td--right" style={{ color: scoreColor(pick.composite_score), fontWeight: 700 }}>
                {pick.composite_score.toFixed(1)}
              </td>
              <td className="stock-table__td stock-table__td--right">{pick.indicators.ibd_rs_percentile.toFixed(0)}</td>
              <td className="stock-table__td stock-table__td--right">{pick.score_breakdown.trend_score.toFixed(0)}</td>
              <td className="stock-table__td stock-table__td--right" style={{ color: pick.score_breakdown.pattern_score >= 50 ? '#f0883e' : '#8b949e' }}>
                {pick.score_breakdown.pattern_score.toFixed(0)}
              </td>
              <td className="stock-table__td stock-table__td--right">{pick.indicators.adx_14.toFixed(1)}</td>
              <td className="stock-table__td stock-table__td--right">{pick.indicators.rsi_14.toFixed(1)}</td>
              <td className="stock-table__td stock-table__td--right">
                <span style={{ color: pick.indicators.cmf_20 >= 0 ? '#26a641' : '#da3633' }}>
                  {pick.indicators.cmf_20 >= 0 ? '+' : ''}{pick.indicators.cmf_20.toFixed(2)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
