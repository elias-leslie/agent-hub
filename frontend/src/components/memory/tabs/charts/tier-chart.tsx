import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { MemoryAnalyticsState } from '@/lib/memory-api'
import { EmptyChart } from '../analytics-components'
import { TIER_COLORS, TIER_LABELS } from '../analytics-constants'

interface TierChartProps {
  data: MemoryAnalyticsState['tier_distribution']
  onTierClick?: (tier: string) => void
}

export function TierChart({ data, onTierClick }: TierChartProps) {
  if (data.length === 0) return <EmptyChart label="No type data" />

  const chartData = data.map((d) => ({
    name: TIER_LABELS[d.tier] || d.tier,
    count: d.count,
    percentage: d.percentage,
    fill: TIER_COLORS[d.tier] || '#64748b',
  }))

  return (
    <div className="space-y-3">
      <div className="h-48">
        <ResponsiveContainer
          width="100%"
          height="100%"
          minWidth={0}
          minHeight={0}
        >
          <BarChart data={chartData} layout="vertical" barCategoryGap="30%">
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="name"
              width={80}
              tick={{ fill: '#94a3b8', fontSize: 12 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const d = payload[0].payload
                return (
                  <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 shadow-xl">
                    <p className="text-sm font-medium text-slate-100">
                      {d.name}
                    </p>
                    <p className="text-xs text-slate-400">
                      {d.count} episodes ({d.percentage}%)
                    </p>
                  </div>
                )
              }}
            />
            <Bar
              dataKey="count"
              radius={[0, 4, 4, 0]}
              maxBarSize={24}
              cursor={onTierClick ? 'pointer' : undefined}
              onClick={(_data, _index, e) => {
                const target = e?.target as SVGElement | undefined
                const barIndex = target
                  ? chartData.findIndex(
                      (d) => d.fill === target.getAttribute('fill'),
                    )
                  : -1
                const entry = barIndex >= 0 ? chartData[barIndex] : null
                const tierKey = entry
                  ? Object.entries(TIER_LABELS).find(
                      ([, label]) => label === entry.name,
                    )?.[0]
                  : null
                if (tierKey && onTierClick) onTierClick(tierKey)
              }}
            >
              {chartData.map((entry) => (
                <Cell key={entry.name} fill={entry.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="flex gap-4 justify-center">
        {chartData.map((d) => (
          <div
            key={d.name}
            className="flex items-center gap-1.5 text-xs text-slate-400"
          >
            <span
              className="w-2.5 h-2.5 rounded-sm"
              style={{ backgroundColor: d.fill }}
            />
            {d.name} ({d.count})
          </div>
        ))}
      </div>
    </div>
  )
}
