'use client'

import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { SpendBar, SpendRange } from '@/lib/api/analytics'
import { bucketLabel, KIND_META, KIND_ORDER, usd } from '../format'

interface TooltipProps {
  active?: boolean
  payload?: Array<{ payload: SpendBar }>
  range: SpendRange
}

function BarTooltip({ active, payload, range }: TooltipProps) {
  const bar = payload?.[0]?.payload
  if (!active || !bar) return null
  const total = KIND_ORDER.reduce((sum, k) => sum + bar[k], 0)
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 shadow-lg">
      <p className="mb-1 font-medium">
        {bucketLabel(bar.start, range)} · {usd(total)}
      </p>
      {KIND_ORDER.filter((k) => bar[k] > 0).map((k) => (
        <p key={k} className="flex items-center gap-1.5 text-slate-400">
          <span className={`h-2 w-2 rounded-sm ${KIND_META[k].dot}`} />
          {KIND_META[k].label} {usd(bar[k])}
        </p>
      ))}
      <p className="mt-1 text-slate-500">Click to see what ran</p>
    </div>
  )
}

export function SpendChart({
  bars,
  range,
  selected,
  onSelect,
}: {
  bars: SpendBar[]
  range: SpendRange
  selected: string | null
  onSelect: (start: string | null) => void
}) {
  const selectedMs = selected ? new Date(selected).getTime() : null
  const isSelected = (bar: SpendBar) =>
    selectedMs != null && new Date(bar.start).getTime() === selectedMs
  const pick = (data: unknown) => {
    const bar = (data as { payload?: SpendBar } | undefined)?.payload
    if (!bar) return
    onSelect(isSelected(bar) ? null : bar.start)
  }

  return (
    <div
      className="h-52 sm:h-60"
      role="img"
      aria-label="Spend over time by kind"
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={bars} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <XAxis
            dataKey="start"
            tickFormatter={(v: string) => bucketLabel(v, range)}
            tick={{ fontSize: 10, fill: '#64748b' }}
            tickLine={false}
            axisLine={{ stroke: '#1e293b' }}
            minTickGap={24}
          />
          <YAxis
            tickFormatter={(v: number) => usd(v)}
            tick={{ fontSize: 10, fill: '#64748b' }}
            tickLine={false}
            axisLine={false}
            width={52}
          />
          <Tooltip
            cursor={{ fill: 'rgba(148,163,184,0.08)' }}
            content={<BarTooltip range={range} />}
          />
          {KIND_ORDER.map((kind, i) => (
            <Bar
              key={kind}
              dataKey={kind}
              stackId="spend"
              fill={KIND_META[kind].color}
              radius={i === KIND_ORDER.length - 1 ? [3, 3, 0, 0] : 0}
              onClick={pick}
              className="cursor-pointer"
              isAnimationActive={false}
            >
              {bars.map((bar) => (
                <Cell
                  key={bar.start}
                  fillOpacity={
                    selectedMs == null || isSelected(bar) ? 0.9 : 0.25
                  }
                />
              ))}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
