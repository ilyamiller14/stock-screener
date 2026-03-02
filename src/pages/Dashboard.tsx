import { useState } from 'react'
import { StockCard } from '../components/StockCard'
import { StockTable } from '../components/StockTable'
import { useScreenerData } from '../hooks/useScreenerData'
import type { TopPick } from '../types/screener'
import './Dashboard.css'

type ViewMode = 'cards' | 'table'

export default function Dashboard() {
  const { data, isLoading, error, refetch } = useScreenerData()
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

  if (!data) return null

  const sectors = ['All', ...Array.from(new Set(data.top_picks.map((p) => p.sector))).sort()]
  const filtered: TopPick[] =
    sectorFilter === 'All'
      ? data.top_picks
      : data.top_picks.filter((p) => p.sector === sectorFilter)

  const runDate = new Date(data.run_timestamp)
  const dateStr = runDate.toLocaleDateString('en-US', {
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
        <span className="legend-item" style={{ color: '#238636' }}>Trend 35%</span>
        <span className="legend-sep">·</span>
        <span className="legend-item" style={{ color: '#58a6ff' }}>Rel. Strength 25%</span>
        <span className="legend-sep">·</span>
        <span className="legend-item" style={{ color: '#bc8cff' }}>Volume 20%</span>
        <span className="legend-sep">·</span>
        <span className="legend-item" style={{ color: '#e3b341' }}>Momentum 15%</span>
        <span className="legend-sep">·</span>
        <span className="legend-item" style={{ color: '#26a641' }}>Stage 2 5%</span>
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
      {view === 'cards' ? (
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
