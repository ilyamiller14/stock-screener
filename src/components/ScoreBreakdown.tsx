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

const CATEGORIES = [
  { key: 'trend_score',    label: 'Trend',           color: '#238636', weight: '30%' },
  { key: 'rs_score',       label: 'IBD Rel. Strength', color: '#58a6ff', weight: '25%' },
  { key: 'volume_score',   label: 'Volume/Accum',    color: '#bc8cff', weight: '15%' },
  { key: 'momentum_score', label: 'Momentum',        color: '#e3b341', weight: '15%' },
  { key: 'pattern_score',  label: 'Pattern',         color: '#f0883e', weight: '15%' },
] as const

export function ScoreBreakdown({ breakdown }: Props) {
  const data = CATEGORIES.map((cat) => ({
    label:  cat.label,
    weight: cat.weight,
    score:  breakdown[cat.key],
    color:  cat.color,
  }))

  return (
    <div className="score-breakdown">
      <div className="score-breakdown__title">Score Breakdown</div>
      <ResponsiveContainer width="100%" height={160}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 50, bottom: 4, left: 100 }}
        >
          <XAxis type="number" domain={[0, 100]} tick={{ fill: '#6e7681', fontSize: 10 }} />
          <YAxis
            type="category"
            dataKey="label"
            tick={{ fill: '#8b949e', fontSize: 11 }}
            width={95}
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
    </div>
  )
}
