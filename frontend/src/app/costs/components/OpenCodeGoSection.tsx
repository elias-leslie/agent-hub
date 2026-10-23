'use client'

import { useQuery } from '@tanstack/react-query'
import {
  fetchOpenCodeGoUsage,
  type OpenCodeGoWindow,
} from '@/lib/api/analytics'
import { cn } from '@/lib/utils'
import { timeUntil } from './PlansSection'

function WindowRow({ w }: { w: OpenCodeGoWindow }) {
  const limited = w.status === 'rate-limited'
  const reset = timeUntil(w.resets_at)
  const color =
    limited || w.percent >= 100
      ? 'bg-red-500'
      : w.percent >= 80
        ? 'bg-amber-500'
        : 'bg-emerald-500'
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
        <span className="text-slate-200">
          {w.label} <span className="font-mono">{w.percent}%</span>
          {limited && <span className="ml-2 text-red-300">Rate limited</span>}
        </span>
        <span className="text-xs text-slate-400">
          {reset ? `Resets ${reset}` : ''}
        </span>
      </div>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-slate-800"
        role="meter"
        aria-label={`${w.label} used`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={w.percent}
      >
        <div
          className={cn('h-full', color)}
          style={{ width: `${Math.min(w.percent, 100)}%` }}
        />
      </div>
    </div>
  )
}

/** OpenCode Go quota (used through Pi), straight from OpenCode's usage endpoint. */
export function OpenCodeGoSection() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['opencode-go-usage'],
    queryFn: fetchOpenCodeGoUsage,
    refetchInterval: 60_000,
  })

  let body: React.ReactNode
  if (isLoading) {
    body = <div className="h-24 animate-pulse rounded-xl bg-slate-800/60" />
  } else if (error || !data) {
    body = <p className="text-sm text-slate-400">Unavailable</p>
  } else if (data.state === 'ok') {
    body = (
      <div className="space-y-3">
        {data.windows.map((w) => (
          <WindowRow key={w.key} w={w} />
        ))}
      </div>
    )
  } else {
    body = (
      <div className="text-sm">
        <p className="text-slate-300">
          {data.state === 'not_configured' ? 'Not set up' : 'Unavailable'}
        </p>
        {data.reason && <p className="mt-1 text-slate-400">{data.reason}</p>}
      </div>
    )
  }

  return (
    <section id="opencode-go" className="panel-surface scroll-mt-4 p-5 lg:p-6">
      <div className="mb-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
          OpenCode Go limits used
        </p>
        <p className="mt-1 text-xs text-slate-400">
          Reported by OpenCode through an unofficial endpoint, so it can change
          without notice.
        </p>
      </div>
      <div className="max-w-xl">{body}</div>
    </section>
  )
}
