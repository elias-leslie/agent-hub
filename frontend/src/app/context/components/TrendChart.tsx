'use client'

import {
  Area,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Trend, TrendStep } from '@/lib/api/context-observability'
import {
  CAUSE_META,
  PART_COLOR,
  shortDate,
  shortDateTime,
  signedPct,
  signedTok,
  tok,
} from '../format'

interface DayDatum {
  x: number
  day: string
  n: number
  total: number | null
  harness: number | null
  ours: number | null
  brief: number | null
}
interface PointDatum {
  x: number
  y: number
  at: string
  version: string | null
  model: string | null
  kind: 'start'
}
interface StepDatum {
  x: number
  y: number
  step: TrendStep
  kind: 'step'
}

function DiamondShape(props: {
  cx?: number
  cy?: number
  payload?: StepDatum
  selected: string | null
}) {
  const { cx, cy, payload, selected } = props
  if (cx == null || cy == null || !payload) return null
  const color = CAUSE_META[payload.step.cause]?.color ?? '#64748b'
  const on = selected === payload.step.at
  const r = on ? 8 : 6
  return (
    <g>
      <path
        d={`M${cx},${cy - r} L${cx + r},${cy} L${cx},${cy + r} L${cx - r},${cy} Z`}
        fill={color}
        stroke={on ? '#f8fafc' : '#0f172a'}
        strokeWidth={on ? 2 : 1.5}
      />
    </g>
  )
}

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean
  payload?: Array<{ payload: DayDatum | PointDatum | StepDatum }>
}) {
  const item = payload?.[0]?.payload
  if (!active || !item) return null
  const box =
    'max-w-xs rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 shadow-lg'
  if ('step' in item) {
    const s = item.step
    return (
      <div className={box}>
        <p className="mb-1 font-medium">
          {shortDateTime(s.at)} ·{' '}
          <span style={{ color: CAUSE_META[s.cause]?.color }}>
            {CAUSE_META[s.cause]?.label ?? s.cause}
          </span>
        </p>
        <p className="text-slate-300">{s.summary}</p>
        {s.markers.length > 0 && (
          <ul className="mt-1 space-y-0.5 text-slate-400">
            {s.markers.map((m) => (
              <li key={`${m.kind}-${m.at}-${m.label}`}>
                {m.kind}: {m.label}
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }
  if ('day' in item) {
    return (
      <div className={box}>
        <p className="mb-1 font-medium">
          {shortDate(`${item.day}T12:00:00Z`)} · median of {item.n}{' '}
          {item.n === 1 ? 'start' : 'starts'}
        </p>
        <p>Total {tok(item.total)}</p>
        <p style={{ color: PART_COLOR.harness }}>Harness {tok(item.harness)}</p>
        <p style={{ color: PART_COLOR.ours }}>Ours {tok(item.ours)}</p>
        <p style={{ color: PART_COLOR.brief }}>Brief {tok(item.brief)}</p>
      </div>
    )
  }
  return (
    <div className={box}>
      <p className="font-medium">
        {shortDateTime(item.at)} · {tok(item.y)}
      </p>
      <p className="text-slate-400">
        {item.version ?? '—'} · {item.model ?? '—'}
      </p>
    </div>
  )
}

export function TrendChart({
  trend,
  selected,
  onSelect,
}: {
  trend: Trend
  selected: string | null
  onSelect: (at: string | null) => void
}) {
  const end = new Date(trend.generated_at).getTime()
  const start = end - trend.days * 86_400_000
  const daily: DayDatum[] = trend.daily.map((d) => ({
    x: Date.parse(`${d.day}T12:00:00Z`),
    day: d.day,
    n: d.n,
    total: d.total,
    harness: d.harness_tokens,
    ours: d.ours,
    brief: d.brief,
  }))
  const points: PointDatum[] = trend.points.map((p) => ({
    x: new Date(p.at).getTime(),
    y: p.total,
    at: p.at,
    version: p.version,
    model: p.model,
    kind: 'start',
  }))
  const steps: StepDatum[] = trend.steps.map((s) => ({
    x: new Date(s.at).getTime(),
    y: s.after_total ?? 0,
    step: s,
    kind: 'step',
  }))
  const versions = trend.versions.filter((v) => !v.initial)
  const ceiling = Math.max(
    trend.warn_tokens ?? 0,
    ...points.map((p) => p.y),
    ...daily.map((d) => d.total ?? 0),
  )
  const parts = [
    ['brief', PART_COLOR.brief],
    ['ours', PART_COLOR.ours],
    ['harness', PART_COLOR.harness],
  ] as const

  return (
    <div
      className="h-64 sm:h-80"
      role="img"
      aria-label={`First-turn tokens over the last ${trend.days} days: daily median by part, one dot per start, and ${steps.length} marked ${steps.length === 1 ? 'step' : 'steps'}`}
    >
      <ResponsiveContainer
        width="100%"
        height="100%"
        initialDimension={{ width: 1, height: 1 }}
      >
        <ComposedChart margin={{ top: 14, right: 8, bottom: 0, left: 0 }}>
          <XAxis
            type="number"
            dataKey="x"
            scale="time"
            domain={[start, end]}
            allowDataOverflow
            tickFormatter={(v: number) => shortDate(new Date(v).toISOString())}
            tick={{ fontSize: 10, fill: '#64748b' }}
            tickLine={false}
            axisLine={{ stroke: '#1e293b' }}
            minTickGap={32}
          />
          <YAxis
            type="number"
            domain={[0, Math.ceil((ceiling * 1.1) / 5000) * 5000 || 10_000]}
            tickFormatter={(v: number) => tok(v)}
            tick={{ fontSize: 10, fill: '#64748b' }}
            tickLine={false}
            axisLine={false}
            width={44}
          />
          <Tooltip
            shared={false}
            cursor={false}
            content={<ChartTooltip />}
            wrapperStyle={{ zIndex: 20, outline: 'none' }}
          />
          {parts.map(([key, color]) => (
            <Area
              key={key}
              data={daily}
              dataKey={key}
              type="stepAfter"
              stackId="parts"
              stroke={color}
              strokeWidth={1}
              fill={color}
              fillOpacity={0.28}
              connectNulls={false}
              isAnimationActive={false}
              activeDot={false}
            />
          ))}
          <Scatter
            data={points}
            dataKey="y"
            shape={(p: unknown) => {
              const { cx, cy } = p as { cx?: number; cy?: number }
              return cx == null || cy == null ? null : (
                <circle
                  cx={cx}
                  cy={cy}
                  r={1.8}
                  fill="#e2e8f0"
                  fillOpacity={0.4}
                />
              )
            }}
            isAnimationActive={false}
            legendType="none"
          />
          {trend.warn_tokens != null && (
            <ReferenceLine
              y={trend.warn_tokens}
              stroke="#f59e0b"
              strokeDasharray="4 3"
              strokeOpacity={0.7}
              label={{
                value: `warn ${tok(trend.warn_tokens)}`,
                position: 'insideTopLeft',
                fill: '#f59e0b',
                fontSize: 10,
              }}
            />
          )}
          {versions.map((v) => (
            <ReferenceLine
              key={v.version}
              x={new Date(v.first_at).getTime()}
              stroke="#a78bfa"
              strokeDasharray="2 3"
              strokeOpacity={0.6}
              label={{
                value: v.version,
                position: 'insideTopRight',
                fill: '#a78bfa',
                fontSize: 10,
                angle: -90,
                dx: -4,
                dy: 24,
              }}
            />
          ))}
          <Scatter
            data={steps}
            dataKey="y"
            isAnimationActive={false}
            legendType="none"
            shape={(p: unknown) => (
              <DiamondShape
                {...(p as { cx?: number; cy?: number; payload?: StepDatum })}
                selected={selected}
              />
            )}
            onClick={(d: unknown) => {
              const at = (d as { payload?: StepDatum })?.payload?.step.at
              if (at) onSelect(selected === at ? null : at)
            }}
            className="cursor-pointer"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

export function stepHeadline(s: TrendStep): string {
  return `${tok(s.before_total)} → ${tok(s.after_total)} (${signedTok(s.delta)}, ${signedPct(s.pct)})`
}
