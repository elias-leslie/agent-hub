'use client'

import type { ReactNode } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type {
  PersonaHeartbeatFieldTrendPoint,
  PersonaImprovementTrendPoint,
} from '@/app/persona/analytics/types'
import { ChartCard } from '@/components/charts/ChartCard'
import { getPersonaDisplayName } from '../../utils/displayName'

interface PersonaImprovementTrendSectionProps {
  labTrend: PersonaImprovementTrendPoint[]
  fieldTrend: PersonaHeartbeatFieldTrendPoint[]
  personaName?: string
}

interface TrendDatum {
  label: string
  completedAt: string | null
  labReliability: number | null
  fieldReliability: number | null
  labEffectiveness: number | null
  fieldEffectiveness: number | null
  labTokens: number | null
  fieldTokens: number | null
}

const TOOLTIP_STYLE = {
  backgroundColor: 'var(--color-slate-950)',
  border: '1px solid var(--color-slate-700)',
  borderRadius: '10px',
  fontSize: '12px',
}

function formatLabel(value: string | null, fallback: string) {
  if (!value) {
    return fallback
  }
  return new Date(value).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function buildChartData(
  labTrend: PersonaImprovementTrendPoint[],
  fieldTrend: PersonaHeartbeatFieldTrendPoint[],
): TrendDatum[] {
  const buckets = new Map<string, TrendDatum & { sortKey: number }>()
  const getBucket = (
    key: string,
    completedAt: string | null,
    fallback: string,
  ) => {
    const existing = buckets.get(key)
    if (existing) {
      return existing
    }
    const sortKey = completedAt
      ? new Date(completedAt).getTime()
      : Number.MAX_SAFE_INTEGER
    const created: TrendDatum & { sortKey: number } = {
      label: formatLabel(completedAt, fallback),
      completedAt,
      labReliability: null,
      fieldReliability: null,
      labEffectiveness: null,
      fieldEffectiveness: null,
      labTokens: null,
      fieldTokens: null,
      sortKey,
    }
    buckets.set(key, created)
    return created
  }

  labTrend.forEach((point, index) => {
    const key = point.completed_at ?? `lab-${index}`
    const bucket = getBucket(key, point.completed_at, `Lab ${index + 1}`)
    bucket.labReliability = point.reliability
    bucket.labEffectiveness = point.effectiveness
    bucket.labTokens = point.tokens_per_passed_attempt
  })

  fieldTrend.forEach((point, index) => {
    const key = point.completed_at ?? `field-${index}`
    const bucket = getBucket(key, point.completed_at, `Field ${index + 1}`)
    bucket.fieldReliability = point.reliability
    bucket.fieldEffectiveness = point.effectiveness
    bucket.fieldTokens = point.total_tokens
  })

  return [...buckets.values()]
    .sort((left, right) => left.sortKey - right.sortKey)
    .map(({ sortKey: _sortKey, ...point }) => point)
}

function EmptyState({ personaName }: { personaName?: string }) {
  return (
    <p className="text-sm text-slate-400">
      No {getPersonaDisplayName(personaName)} trend data yet.
    </p>
  )
}

function TrendLegend() {
  return (
    <div className="mb-3 flex flex-wrap gap-3 text-[11px] uppercase tracking-wide text-slate-400">
      <span className="inline-flex items-center gap-2">
        <span
          className="h-2 w-2 rounded-full"
          style={{ backgroundColor: '#34d399' }}
        />
        Lab
      </span>
      <span className="inline-flex items-center gap-2">
        <span
          className="h-2 w-2 rounded-full"
          style={{ backgroundColor: '#60a5fa' }}
        />
        Field
      </span>
    </div>
  )
}

function TrendCard({
  title,
  chartData,
  labKey,
  fieldKey,
  yDomain,
  labLabel,
  fieldLabel,
  emptyState,
}: {
  title: string
  chartData: TrendDatum[]
  labKey: keyof TrendDatum
  fieldKey: keyof TrendDatum
  yDomain?: [number, number]
  labLabel: string
  fieldLabel: string
  emptyState?: ReactNode
}) {
  return (
    <ChartCard title={title}>
      {chartData.length === 0 ? (
        (emptyState ?? <EmptyState />)
      ) : (
        <>
          <TrendLegend />
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 11 }}
                  stroke="#64748b"
                  minTickGap={42}
                />
                <YAxis
                  domain={yDomain}
                  tick={{ fontSize: 11 }}
                  stroke="#64748b"
                  allowDecimals
                />
                <Tooltip
                  formatter={(value, name) => {
                    if (name === labLabel || name === fieldLabel) {
                      const numeric = Number(value ?? 0)
                      if (title === 'Token Spend Trend') {
                        return [numeric.toFixed(0), name]
                      }
                      return [`${numeric.toFixed(1)}%`, name]
                    }
                    return [String(value), String(name)]
                  }}
                  labelFormatter={(value) => String(value)}
                  contentStyle={TOOLTIP_STYLE}
                />
                <Line
                  type="monotone"
                  dataKey={String(labKey)}
                  name={labLabel}
                  stroke="#34d399"
                  strokeWidth={3}
                  dot={{ r: 2 }}
                  activeDot={{ r: 5 }}
                  connectNulls
                />
                <Line
                  type="monotone"
                  dataKey={String(fieldKey)}
                  name={fieldLabel}
                  stroke="#60a5fa"
                  strokeWidth={3}
                  dot={{ r: 2 }}
                  activeDot={{ r: 5 }}
                  connectNulls
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </ChartCard>
  )
}

export function PersonaImprovementTrendSection({
  labTrend,
  fieldTrend,
  personaName,
}: PersonaImprovementTrendSectionProps) {
  const chartData = buildChartData(labTrend, fieldTrend)

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
      <TrendCard
        title="Reliability Trend"
        chartData={chartData}
        labKey="labReliability"
        fieldKey="fieldReliability"
        yDomain={[0, 100]}
        labLabel="Lab reliability"
        fieldLabel="Field reliability"
        emptyState={<EmptyState personaName={personaName} />}
      />
      <TrendCard
        title="Effectiveness Trend"
        chartData={chartData}
        labKey="labEffectiveness"
        fieldKey="fieldEffectiveness"
        yDomain={[0, 100]}
        labLabel="Lab effectiveness"
        fieldLabel="Field effectiveness"
        emptyState={<EmptyState personaName={personaName} />}
      />
      <TrendCard
        title="Token Spend Trend"
        chartData={chartData}
        labKey="labTokens"
        fieldKey="fieldTokens"
        labLabel="Lab tok / pass"
        fieldLabel="Field tok / heartbeat"
        emptyState={<EmptyState personaName={personaName} />}
      />
    </div>
  )
}
