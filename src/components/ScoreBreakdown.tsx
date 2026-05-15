import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ScoreBreakdown as ScoreBreakdownType } from '../types/screener'
import './ScoreBreakdown.css'

interface Props {
  breakdown: ScoreBreakdownType
}

const V2_CATEGORIES = [
  { key: 'trend_strength',    label: 'Trend Strength',    color: '#238636', weight: '30%' },
  { key: 'trend_cleanliness', label: 'Trend Cleanliness', color: '#3fb950', weight: '10%' },
  { key: 'rs',                label: 'Relative Strength', color: '#58a6ff', weight: '25%' },
  { key: 'base_setup',        label: 'Base / Setup',      color: '#f0883e', weight: '20%' },
  { key: 'volume_profile',    label: 'Volume Profile',    color: '#bc8cff', weight: '15%' },
] as const

const V1_CATEGORIES = [
  { key: 'trend_score',    label: 'Trend',           color: '#238636', weight: '30%' },
  { key: 'rs_score',       label: 'IBD Rel. Strength', color: '#58a6ff', weight: '25%' },
  { key: 'volume_score',   label: 'Volume/Accum',    color: '#bc8cff', weight: '15%' },
  { key: 'momentum_score', label: 'Momentum',        color: '#e3b341', weight: '15%' },
  { key: 'pattern_score',  label: 'Pattern',         color: '#f0883e', weight: '15%' },
] as const

export function ScoreBreakdown({ breakdown }: Props) {
  const isV2 = breakdown.trend_strength !== undefined

  const categories = isV2 ? V2_CATEGORIES : V1_CATEGORIES

  const data = categories.map((cat) => ({
    label:  cat.label,
    weight: cat.weight,
    score:  (breakdown as Record<string, unknown>)[cat.key] as number | undefined ?? 0,
    color:  cat.color,
  }))

  return (
    <div className="score-breakdown">
      <div className="score-breakdown__title">Score Breakdown</div>
      <ResponsiveContainer width="100%" height={160}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 50, bottom: 4, left: 110 }}
        >
          <XAxis type="number" domain={[0, 100]} tick={{ fill: '#6e7681', fontSize: 10 }} />
          <YAxis
            type="category"
            dataKey="label"
            tick={{ fill: '#8b949e', fontSize: 11 }}
            width={105}
          />
          <Tooltip
            formatter={(value: number, _name: string, entry) => [
              `${value.toFixed(1)} / 100`,
              `${entry.payload.label} (weight ${entry.payload.weight})`,
            ]}
            contentStyle={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 6 }}
            labelStyle={{ color: '#c9d1d9' }}
            itemStyle={{ color: '#c9d1d9' }}
            cursor={{ fill: '#21262d' }}
          />
          <Bar dataKey="score" radius={[0, 4, 4, 0]}>
            {data.map((entry, i) => (
              <Cell key={i} fill={entry.color} />
            ))}
            <LabelList
              dataKey="score"
              position="right"
              formatter={(v: number) => v.toFixed(0)}
              style={{ fill: '#8b949e', fontSize: 10 }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      {isV2 && breakdown.penalty_triggered && breakdown.penalty_triggered.length > 0 && (
        <div className="score-breakdown__penalties">
          Penalties: {breakdown.penalty_triggered.join(', ')} (× {breakdown.penalty_multiplier?.toFixed(2) ?? '?'})
        </div>
      )}
    </div>
  )
}
