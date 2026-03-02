import { useState } from 'react'
import { StockCard } from '../components/StockCard'
import { StockTable } from '../components/StockTable'
import { useScreenerData } from '../hooks/useScreenerData'
import type { TopPick } from '../types/screener'
import './Dashboard.css'

type ViewMode = 'cards' | 'table'

export default function Dashboard() {
  const { data, isLoading, error, noData, refetch } = useScreenerData()
  const [view, setView] = useState<ViewMode>('cards')
  const [sectorFilter, setSectorFilter] = useState<string>('All')

  if (isLoading) {
    return (
      <div className="dashboard-loading">
        <div className="spinner" />
        <p>Loading screener results…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="dashboard-error">
        <p>Error: {error}</p>
        <button onClick={refetch} className="btn btn--primary">Retry</button>
      </div>
    )
  }

  if (noData || !data) {
    return (
      <div className="dashboard-error">
        <p style={{ fontSize: 18, color: '#c9d1d9' }}>No screening results yet</p>
        <p style={{ maxWidth: 400, textAlign: 'center', lineHeight: 1.6 }}>
          The screener runs daily at 6 AM ET on weekdays. Results will appear here after the first run completes.
        </p>
        <button onClick={refetch} className="btn btn--primary">Check Again</button>
      </div>
    )
  }

  const sectors = ['All', ...Array.from(new Set(data.top_picks.map((p) => p.sector).filter(Boolean))).sort()]
  const filtered: TopPick[] =
    sectorFilter === 'All'
      ? data.top_picks
      : data.top_picks.filter((p) => p.sector === sectorFilter)

  const runDate = new Date(data.run_timestamp)
  const dateStr = isNaN(runDate.getTime())
    ? data.run_date
    : runDate.toLocaleDateString('en-US', {
        weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
      })

  return (
    <div className="dashboard">
      {/* Summary bar */}
      <div className="dashboard__summary">
        <div className="summary__date">{dateStr}</div>
        <div className="summary__stats">
          <div className="stat">
            <span className="stat__label">Screened</span>
            <span className="stat__value">{data.screened_count.toLocaleString()}</span>
          </div>
          <div className="stat">
            <span className="stat__label">Qualifying</span>
            <span className="stat__value stat__value--green">{data.qualifying_count.toLocaleString()}</span>
          </div>
          <div className="stat">
            <span className="stat__label">Top Picks</span>
            <span className="stat__value stat__value--blue">{data.top_picks.length}</span>
          </div>
        </div>
      </div>

      {/* Scoring legend */}
      <div className="dashboard__legend">
        <span className="legend-item" style={{ color: '#238636' }}>Trend 30%</span>
        <span className="legend-sep">·</span>
        <span className="legend-item" style={{ color: '#58a6ff' }}>IBD Rel. Strength 25%</span>
        <span className="legend-sep">·</span>
        <span className="legend-item" style={{ color: '#bc8cff' }}>Volume 15%</span>
        <span className="legend-sep">·</span>
        <span className="legend-item" style={{ color: '#e3b341' }}>Momentum 15%</span>
        <span className="legend-sep">·</span>
        <span className="legend-item" style={{ color: '#f0883e' }}>Pattern (VCP/Squeeze/S2) 15%</span>
      </div>

      {/* Controls */}
      <div className="dashboard__controls">
        <div className="control-group">
          <select
            className="select"
            value={sectorFilter}
            onChange={(e) => setSectorFilter(e.target.value)}
          >
            {sectors.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <div className="view-toggle">
          <button
            className={`view-btn ${view === 'cards' ? 'view-btn--active' : ''}`}
            onClick={() => setView('cards')}
          >
            Cards
          </button>
          <button
            className={`view-btn ${view === 'table' ? 'view-btn--active' : ''}`}
            onClick={() => setView('table')}
          >
            Table
          </button>
        </div>
      </div>

      {/* Content */}
      {filtered.length === 0 ? (
        <div className="dashboard-error" style={{ minHeight: 120 }}>
          <p>No stocks found in this sector.</p>
          <button onClick={() => setSectorFilter('All')} className="btn btn--primary">Show All</button>
        </div>
      ) : view === 'cards' ? (
        <div className="dashboard__grid">
          {filtered.map((pick) => (
            <StockCard key={pick.ticker} pick={pick} />
          ))}
        </div>
      ) : (
        <StockTable picks={filtered} />
      )}
    </div>
  )
}
