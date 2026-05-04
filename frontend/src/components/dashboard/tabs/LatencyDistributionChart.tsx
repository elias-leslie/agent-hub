'use client'

import { Timer } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  fetchModelLatencyStats,
  type ModelLatencyStats,
} from '@/lib/api/dashboard'
import { formatModelName } from '@/lib/formatters'

export function LatencyDistributionChart() {
  const [stats, setStats] = useState<ModelLatencyStats[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let mounted = true
    ;(async () => {
      try {
        const res = await fetchModelLatencyStats(7)
        if (mounted) setStats(res.stats)
      } catch {
        // silently fail
      } finally {
        if (mounted) setLoading(false)
      }
    })()
    return () => {
      mounted = false
    }
  }, [])

  if (loading)
    return <div className="h-64 bg-slate-800 rounded animate-pulse" />
  if (stats.length === 0)
    return (
      <div className="flex items-center justify-center h-40 text-slate-500 text-xs">
        No latency data available (need at least 10 samples per model)
      </div>
    )

  const chartData = stats.slice(0, 10).map((s) => ({
    model: formatModelName(s.model, 16),
    p50: Math.round(s.p50_ms),
    p95: Math.round(s.p95_ms),
    p99: Math.round(s.p99_ms),
    fullModel: s.model,
    samples: s.sample_count,
  }))

  return (
    <div className="p-4 rounded-lg bg-slate-800/40 border border-slate-700/50">
      <h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
        <Timer className="h-3 w-3" />
        Per-Model Latency Distribution (7d)
      </h4>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ left: 80, right: 20, top: 5, bottom: 5 }}
        >
          <XAxis
            type="number"
            tick={{ fill: '#94a3b8', fontSize: 10 }}
            tickFormatter={(v) => `${(v / 1000).toFixed(1)}s`}
          />
          <YAxis
            type="category"
            dataKey="model"
            tick={{ fill: '#cbd5e1', fontSize: 10 }}
            width={80}
          />
          <Tooltip
            contentStyle={{
              background: '#1e293b',
              border: '1px solid #334155',
              borderRadius: 8,
              fontSize: 11,
            }}
            labelStyle={{ color: '#e2e8f0' }}
            formatter={(value) => [`${(Number(value) / 1000).toFixed(2)}s`]}
            labelFormatter={(label) => {
              const item = chartData.find((d) => d.model === label)
              return `${item?.fullModel || label} (${item?.samples || 0} samples)`
            }}
          />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          <Bar dataKey="p50" fill="#10b981" name="P50" radius={[0, 2, 2, 0]} />
          <Bar dataKey="p95" fill="#f59e0b" name="P95" radius={[0, 2, 2, 0]} />
          <Bar dataKey="p99" fill="#ef4444" name="P99" radius={[0, 2, 2, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
