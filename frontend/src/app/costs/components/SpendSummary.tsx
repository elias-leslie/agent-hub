import type { SpendSummary as Summary } from '@/lib/api/analytics'
import { cn } from '@/lib/utils'
import { usd } from '../format'

function Versus({
  ratio,
  typical,
  unit = '',
}: {
  ratio: number | null
  typical: number | null
  unit?: string
}) {
  if (ratio == null || typical == null) {
    return <span className="text-slate-500">No usual level yet</span>
  }
  const tone =
    ratio >= 3
      ? 'text-red-300'
      : ratio >= 1.5
        ? 'text-amber-300'
        : 'text-slate-400'
  return (
    <span className={tone}>
      {ratio >= 0.95 && ratio <= 1.05 ? 'About usual' : `${ratio}× usual`}
      <span className="text-slate-500">
        {' '}
        ({usd(typical)}
        {unit})
      </span>
    </span>
  )
}

function Tile({
  label,
  value,
  children,
}: {
  label: string
  value: string
  children: React.ReactNode
}) {
  return (
    <div className="rounded-2xl border border-slate-800/80 bg-slate-900/65 px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
        {label}
      </p>
      <p className="mt-1 font-mono text-2xl font-semibold text-slate-100 lg:text-3xl">
        {value}
      </p>
      <p className="mt-1 text-xs">{children}</p>
    </div>
  )
}

export function SpendSummary({
  summary,
  loading,
}: {
  summary: Summary | undefined
  loading: boolean
}) {
  if (loading || !summary) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className={cn(
              'h-[98px] rounded-2xl bg-slate-800/50',
              'animate-pulse',
            )}
          />
        ))}
      </div>
    )
  }
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Tile label="Spending now" value={`${usd(summary.rate_per_hour)}/hr`}>
        <Versus
          ratio={summary.rate_ratio}
          typical={summary.rate_typical}
          unit="/hr"
        />
      </Tile>
      <Tile label="Today" value={usd(summary.today)}>
        <Versus ratio={summary.today_ratio} typical={summary.today_typical} />
      </Tile>
      <Tile label="Last 7 days" value={usd(summary.week)}>
        <Versus ratio={summary.week_ratio} typical={summary.week_typical} />
      </Tile>
    </div>
  )
}
