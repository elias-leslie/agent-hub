import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { AgentBenchmarkTrendPoint } from '../types'
import { ChartCard } from './ChartCard'

interface BenchmarkTrendSectionProps {
  trend: AgentBenchmarkTrendPoint[]
}

function buildChartData(trend: AgentBenchmarkTrendPoint[]) {
  return trend.map((point, index) => ({
    ...point,
    label: point.completed_at
      ? new Date(point.completed_at).toLocaleString([], {
          month: 'short',
          day: 'numeric',
          hour: 'numeric',
          minute: '2-digit',
        })
      : `Run ${index + 1}`,
    score: point.avg_score ?? 0,
    passRate: point.pass_rate ?? 0,
  }))
}

export function BenchmarkTrendSection({ trend }: BenchmarkTrendSectionProps) {
  const chartData = buildChartData(trend)

  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 mb-6">
      <ChartCard title="Benchmark Score Trend">
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11 }}
                stroke="#94a3b8"
                minTickGap={48}
              />
              <YAxis
                domain={[0, 100]}
                tick={{ fontSize: 11 }}
                stroke="#94a3b8"
              />
              <Tooltip
                formatter={(value) => [
                  `${Number(value ?? 0).toFixed(1)}`,
                  'Avg score',
                ]}
                labelFormatter={(value) => String(value)}
                contentStyle={{
                  backgroundColor: '#0f172a',
                  border: 'none',
                  borderRadius: '10px',
                  fontSize: '12px',
                }}
              />
              <Line
                type="monotone"
                dataKey="score"
                stroke="#0f766e"
                strokeWidth={3}
                dot={{ r: 2 }}
                activeDot={{ r: 5 }}
                name="Avg score"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>

      <ChartCard title="Benchmark Pass Trend">
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11 }}
                stroke="#94a3b8"
                minTickGap={48}
              />
              <YAxis
                domain={[0, 100]}
                tick={{ fontSize: 11 }}
                stroke="#94a3b8"
              />
              <Tooltip
                formatter={(value) => [
                  `${Number(value ?? 0).toFixed(1)}%`,
                  'Pass rate',
                ]}
                labelFormatter={(value) => String(value)}
                contentStyle={{
                  backgroundColor: '#0f172a',
                  border: 'none',
                  borderRadius: '10px',
                  fontSize: '12px',
                }}
              />
              <Line
                type="monotone"
                dataKey="passRate"
                stroke="#2563eb"
                strokeWidth={3}
                dot={{ r: 2 }}
                activeDot={{ r: 5 }}
                name="Pass rate"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </ChartCard>
    </div>
  )
}
