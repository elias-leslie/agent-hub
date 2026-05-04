import {
  Bar,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { MetricsDashboard } from '@/lib/memory-api'
import { EmptyChart } from '../analytics-components'

interface InjectionMetricsChartProps {
  data: MetricsDashboard | undefined
}

export function InjectionMetricsChart({ data }: InjectionMetricsChartProps) {
  if (!data || data.by_period.length === 0) {
    return <EmptyChart label="No injection metrics for this period" />
  }

  const formatPeriodLabel = (period: string) => {
    if (period.includes(' ')) {
      return period.slice(11, 16)
    }
    if (period.includes('-W')) {
      return period.slice(2)
    }
    return period.slice(5)
  }

  const chartData = data.by_period.map((d) => ({
    period: formatPeriodLabel(d.period),
    injections: d.injection_count,
    successRate: Math.round(d.avg_success_rate * 100),
    citationRate: Math.round(d.avg_citation_rate * 100),
  }))

  return (
    <div className="h-64">
      <ResponsiveContainer
        width="100%"
        height="100%"
        minWidth={0}
        minHeight={0}
      >
        <ComposedChart data={chartData} barCategoryGap="20%">
          <XAxis
            dataKey="period"
            tick={{ fill: '#64748b', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            interval={Math.max(0, Math.floor(chartData.length / 10) - 1)}
          />
          <YAxis
            yAxisId="left"
            allowDecimals={false}
            tick={{ fill: '#64748b', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={35}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            domain={[0, 100]}
            tick={{ fill: '#64748b', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={35}
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null
              return (
                <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 shadow-xl">
                  <p className="text-xs text-slate-400 mb-1">{label}</p>
                  {payload.map((p) => (
                    <p
                      key={p.dataKey as string}
                      className="text-xs text-slate-200"
                    >
                      <span style={{ color: p.color }}>{p.name}</span>:{' '}
                      {p.dataKey === 'injections' ? p.value : `${p.value}%`}
                    </p>
                  ))}
                </div>
              )
            }}
          />
          <Bar
            yAxisId="left"
            dataKey="injections"
            name="Injections"
            fill="#475569"
            radius={[3, 3, 0, 0]}
            maxBarSize={24}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="successRate"
            name="Success %"
            stroke="#22c55e"
            strokeWidth={2}
            dot={false}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="citationRate"
            name="Citation %"
            stroke="#a855f7"
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <div className="flex gap-5 justify-center mt-2">
        <div className="flex items-center gap-1.5 text-xs text-slate-400">
          <span className="w-3 h-2 rounded-sm bg-slate-600" />
          Injections
        </div>
        <div className="flex items-center gap-1.5 text-xs text-slate-400">
          <span className="w-3 h-0.5 rounded-full bg-green-500" />
          Success %
        </div>
        <div className="flex items-center gap-1.5 text-xs text-slate-400">
          <span className="w-3 h-0.5 rounded-full bg-purple-500" />
          Citation %
        </div>
      </div>
    </div>
  )
}
