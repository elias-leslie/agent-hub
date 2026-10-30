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
  cash,
  children,
}: {
  label: string
  value: string
  /** Cash actually paid over the same period, already formatted; omitted when it doesn't apply. */
  cash?: string
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
      {cash !== undefined && (
        <p className="mt-1 text-xs text-slate-400">
          Cash paid <span className="font-mono text-slate-200">{cash}</span>
        </p>
      )}
    </div>
  )
}

/** Formatted cash paid today and over the last 7 days ('…' while loading, 'unavailable' on failure). */
export interface CashPaid {
  today: string
  week: string
}

export function SpendSummary({
  summary,
  loading,
  cash,
}: {
  summary: Summary | undefined
  loading: boolean
  cash?: CashPaid
}) {
  if (loading || !summary) {
    return (
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className={cn(
              'h-[122px] rounded-2xl bg-slate-800/50',
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
      <Tile label="Today" value={usd(summary.today)} cash={cash?.today}>
        <Versus ratio={summary.today_ratio} typical={summary.today_typical} />
      </Tile>
      <Tile label="Last 7 days" value={usd(summary.week)} cash={cash?.week}>
        <Versus ratio={summary.week_ratio} typical={summary.week_typical} />
      </Tile>
    </div>
  )
}
