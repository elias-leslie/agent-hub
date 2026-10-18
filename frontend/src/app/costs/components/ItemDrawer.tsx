'use client'

import { useQuery } from '@tanstack/react-query'
import { ExternalLink, X } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useRef } from 'react'
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from 'recharts'
import { fetchSpendItem, type SpendRange } from '@/lib/api/analytics'
import { formatModelName } from '@/lib/formatters'
import { bucketLabel, KIND_META, RANGE_LABEL, tokens, usd } from '../format'

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="border-t border-slate-800 pt-4">
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
        {title}
      </h3>
      {children}
    </section>
  )
}

function Line({
  label,
  value,
  sub,
}: {
  label: string
  value: string
  sub?: string
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1 text-sm">
      <span className="min-w-0 truncate text-slate-300" title={label}>
        {label}
      </span>
      <span className="shrink-0 font-mono text-slate-100">
        {value}
        {sub && <span className="ml-2 text-xs text-slate-500">{sub}</span>}
      </span>
    </div>
  )
}

/** "session:claude:<id>" opens on the Sessions page; jobs have no single session. */
function sessionId(key: string): string | null {
  const parts = key.split(':')
  return parts[0] === 'session' && parts.length >= 3
    ? parts.slice(2).join(':')
    : null
}

export function ItemDrawer({
  itemKey,
  range,
  onClose,
}: {
  itemKey: string
  range: SpendRange
  onClose: () => void
}) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const { data, isLoading, error } = useQuery({
    queryKey: ['spend-item', itemKey, range],
    queryFn: () => fetchSpendItem(itemKey, range),
    refetchInterval: 60_000,
  })

  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const sid = sessionId(itemKey)
  const kind = data?.kind ? KIND_META[data.kind] : null

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close details"
        className="absolute inset-0 bg-slate-950/60"
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={data?.name ?? 'Cost details'}
        className="relative flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-slate-800 bg-slate-950 p-5 shadow-2xl"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="break-words text-base font-semibold text-slate-100">
              {data?.name ?? (isLoading ? 'Loading…' : itemKey)}
            </h2>
            {data && (
              <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-slate-400">
                {kind && (
                  <span className="inline-flex items-center gap-1.5">
                    <span className={`h-2 w-2 rounded-full ${kind.dot}`} />
                    {kind.label}
                  </span>
                )}
                {data.project && <span>· {data.project}</span>}
                <span>· {RANGE_LABEL[range]}</span>
              </p>
            )}
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="icon-button shrink-0"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {error ? (
          <p className="text-sm text-red-400">
            Couldn't load this:{' '}
            {error instanceof Error ? error.message : 'unknown error'}
          </p>
        ) : isLoading || !data ? (
          <div className="space-y-3">
            <div className="h-16 animate-pulse rounded-xl bg-slate-800/50" />
            <div className="h-32 animate-pulse rounded-xl bg-slate-800/50" />
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.14em] text-slate-500">
                  Cost
                </p>
                <p className="font-mono text-xl text-slate-100">
                  {usd(data.total_usd)}
                </p>
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-[0.14em] text-slate-500">
                  Tokens
                </p>
                <p className="font-mono text-xl text-slate-100">
                  {tokens(data.tokens)}
                </p>
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-[0.14em] text-slate-500">
                  Model calls
                </p>
                <p className="font-mono text-xl text-slate-100">
                  {data.calls.toLocaleString()}
                </p>
              </div>
            </div>

            <div className="h-28">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={data.timeline}
                  margin={{ top: 4, right: 0, bottom: 0, left: 0 }}
                >
                  <XAxis
                    dataKey="start"
                    tickFormatter={(v: string) => bucketLabel(v, range)}
                    tick={{ fontSize: 10, fill: '#64748b' }}
                    tickLine={false}
                    axisLine={{ stroke: '#1e293b' }}
                    minTickGap={24}
                  />
                  <Tooltip
                    cursor={{ fill: 'rgba(148,163,184,0.08)' }}
                    formatter={(v) => [usd(Number(v)), 'Cost']}
                    labelFormatter={(v) => bucketLabel(String(v), range)}
                    contentStyle={{
                      background: '#020617',
                      border: '1px solid #334155',
                      borderRadius: 8,
                      fontSize: 12,
                      color: '#e2e8f0',
                    }}
                  />
                  <Bar
                    dataKey="usd"
                    fill={kind?.color ?? '#94a3b8'}
                    radius={[2, 2, 0, 0]}
                    isAnimationActive={false}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {data.runs && (
              <Section title="Runs">
                <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-4">
                  <Line
                    label="Count"
                    value={data.runs.count.toLocaleString()}
                  />
                  <Line label="Per day" value={String(data.runs.per_day)} />
                  <Line label="Per run" value={usd(data.runs.cost_per_run)} />
                  <Line label="Median run" value={usd(data.runs.median_run)} />
                </div>
              </Section>
            )}

            {data.agents.length > 0 && (
              <Section
                title={
                  data.runs ? 'Where it went' : 'Main session and sub-agents'
                }
              >
                {data.agents.slice(0, 12).map((a) => (
                  <Line
                    key={a.key}
                    label={a.name}
                    value={usd(a.usd)}
                    sub={`${a.calls.toLocaleString()} calls`}
                  />
                ))}
                {data.agents.length > 12 && (
                  <p className="pt-1 text-xs text-slate-500">
                    and {data.agents.length - 12} more
                  </p>
                )}
              </Section>
            )}

            <Section title="Models">
              {data.models.map((m) => (
                <Line
                  key={m.model}
                  label={formatModelName(m.model, 32)}
                  value={usd(m.usd)}
                  sub={tokens(m.tokens)}
                />
              ))}
            </Section>

            <Section title="Biggest calls">
              {data.top_calls.map((c) => (
                <Line
                  key={`${c.at}-${c.usd}-${c.agent}`}
                  label={`${new Date(c.at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })} · ${c.agent}`}
                  value={usd(c.usd)}
                  sub={tokens(c.tokens)}
                />
              ))}
            </Section>

            {sid && (
              <Link
                href={`/sessions?sel=${encodeURIComponent(sid)}`}
                className="inline-flex items-center gap-1.5 text-sm text-amber-300 hover:text-amber-200"
              >
                Open this session <ExternalLink className="h-3.5 w-3.5" />
              </Link>
            )}
          </div>
        )}
      </aside>
    </div>
  )
}
