'use client'

import {
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
} from 'recharts'
import type { ModelOption } from '@/components/chat/use-models'

interface ModelRadarProps {
  models: ModelOption[]
  size?: 'sm' | 'md' | 'lg'
}

const CHART_COLORS: Record<string, string> = {
  claude: '#f59e0b', // amber-500
  gemini: '#3b82f6', // blue-500
  openai: '#10b981', // green-500
  openrouter: '#a855f7', // purple-500
  xai: '#ef4444', // red-500
  zhipu: '#14b8a6', // teal-500
  minimax: '#f97316', // orange-500
  nvidia: '#84cc16', // lime-500
}

function buildScoreRow(
  category: string,
  models: ModelOption[],
  getScore: (model: ModelOption) => number,
) {
  const row: Record<string, string | number> = { category }
  models.forEach((model, index) => {
    row[`model${index}`] = getScore(model)
  })
  return row
}

export function ModelRadar({ models, size = 'md' }: ModelRadarProps) {
  if (models.length === 0) return null

  const chartData = [
    buildScoreRow('Coding', models, (model) => model.scores.coding),
    buildScoreRow('Reasoning', models, (model) => model.scores.reasoning),
    buildScoreRow('Planning', models, (model) => model.scores.planning),
    buildScoreRow('Tool Use', models, (model) => model.scores.tool_use),
    buildScoreRow('Instruction', models, (model) => model.scores.instruction),
    buildScoreRow('Design', models, (model) => model.scores.design),
  ]

  const heightMap = {
    sm: 180,
    md: 280,
    lg: 400,
  }

  return (
    <ResponsiveContainer width="100%" height={heightMap[size]}>
      <RadarChart data={chartData}>
        <PolarGrid stroke="#334155" strokeDasharray="3 3" />
        <PolarAngleAxis
          dataKey="category"
          tick={{ fill: '#94a3b8', fontSize: size === 'sm' ? 10 : 12 }}
        />
        <PolarRadiusAxis
          angle={90}
          domain={[0, 100]}
          tick={{ fill: '#64748b', fontSize: 10 }}
        />
        {models.map((model, index) => (
          <Radar
            key={model.id}
            name={model.name}
            dataKey={`model${index}`}
            stroke={CHART_COLORS[model.provider]}
            fill={CHART_COLORS[model.provider]}
            fillOpacity={models.length === 1 ? 0.3 : 0.15}
            strokeWidth={2}
          />
        ))}
        {models.length > 1 && (
          <Legend
            wrapperStyle={{
              fontSize: '12px',
              paddingTop: '10px',
            }}
          />
        )}
      </RadarChart>
    </ResponsiveContainer>
  )
}
