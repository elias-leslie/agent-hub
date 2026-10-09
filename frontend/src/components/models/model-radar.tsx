'use client'

import { useState } from 'react'
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
import { getProviderColor } from '@/components/settings/constants'

interface ModelRadarProps {
  models: ModelOption[]
  size?: 'sm' | 'md' | 'lg'
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

/**
 * Below this chart width the default 80% radius leaves no room for the side
 * axis labels (Instruction, Reasoning), so they clip at phone width.
 */
const NARROW_CHART_WIDTH = 420

export function ModelRadar({
  models: allModels,
  size = 'md',
}: ModelRadarProps) {
  const [chartWidth, setChartWidth] = useState<number | null>(null)
  const narrow = chartWidth !== null && chartWidth < NARROW_CHART_WIDTH
  const models = allModels.filter(
    (model) =>
      !(
        model.capabilities.supports_typed_judgment &&
        !model.capabilities.supports_chat
      ),
  )
  if (models.length === 0)
    return (
      <p className="text-xs text-slate-400">
        Typed judgment models have no comparable generative benchmark rating.
      </p>
    )

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
    <ResponsiveContainer
      width="100%"
      height={heightMap[size]}
      onResize={(width) => setChartWidth(width)}
    >
      <RadarChart data={chartData} outerRadius={narrow ? '56%' : '80%'}>
        <PolarGrid stroke="#334155" strokeDasharray="3 3" />
        <PolarAngleAxis
          dataKey="category"
          tick={{
            fill: '#94a3b8',
            fontSize: size === 'sm' || narrow ? 10 : 12,
          }}
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
            stroke={getProviderColor(model.provider).chart}
            fill={getProviderColor(model.provider).chart}
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
