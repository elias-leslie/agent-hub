'use client'

import { useQuery } from '@tanstack/react-query'
import {
  Ban,
  CircleDollarSign,
  Copy,
  Flame,
  Inbox,
  Tag,
  TrendingUp,
} from 'lucide-react'
import {
  fetchSpendPatterns,
  type SpendPatternsResponse,
} from '@/lib/api/analytics'
import { formatCurrency } from '@/lib/formatters'
import { cn } from '@/lib/utils'
import { Card, Row } from './CostAccountingSection'

const WARN = 'text-amber-800 dark:text-amber-300'

const GATE_REASONS: Record<string, string> = {
  project_disabled: 'project automations off',
  profile_disabled: 'automation off',
  project_permission_off: 'project permission off',
  persona_missing: 'no persona',
  persona_not_onboarded: 'persona not set up',
  persona_paused: 'persona paused',
  heartbeat_interval_disabled: 'heartbeat off',
  definition_missing: 'definition missing',
}

function gateReason(reason: string): string {
  return GATE_REASONS[reason] ?? reason.replaceAll('_', ' ')
}

function count(n: number): string {
  return n.toLocaleString()
}

function plural(n: number, noun: string): string {
  return `${count(n)} ${noun}${n === 1 ? '' : 's'}`
}

function percent(share: number): string {
  return `${Math.round(share * 100)}%`
}

function Headline({
  warn,
  children,
}: {
  warn?: boolean
  children: React.ReactNode
}) {
  return (
    <p className={cn('mb-3 text-sm', warn ? WARN : 'text-slate-200')}>
      {children}
    </p>
  )
}

function Unavailable() {
  return <p className="text-sm text-slate-400">Couldn't load this one.</p>
}

function UnpricedCard({ data }: { data: SpendPatternsResponse['unpriced'] }) {
  return (
    <Card title="Calls with no price" icon={CircleDollarSign}>
      {!data ? (
        <Unavailable />
      ) : data.unpriced_calls === 0 ? (
        <Headline>All {count(data.calls)} calls have a price.</Headline>
      ) : (
        <>
          <Headline warn>
            {count(data.unpriced_calls)} of {count(data.calls)} calls used
            tokens but have no price.
          </Headline>
          <div className="space-y-1.5">
            {data.models.map((m) => (
              <Row
                key={m.model}
                label={m.model}
                value={plural(m.calls, 'call')}
              />
            ))}
          </div>
        </>
      )}
    </Card>
  )
}

function EffortCard({ data }: { data: SpendPatternsResponse['effort'] }) {
  return (
    <Card title="Effort level" icon={Flame}>
      {!data ? (
        <Unavailable />
      ) : data.sessions_with_effort === 0 ? (
        <Headline>No sessions recorded an effort level.</Headline>
      ) : (
        <>
          <Headline warn={(data.high_session_share ?? 0) >= 0.5}>
            {percent(data.high_session_share ?? 0)} of sessions ran at xhigh or
            max
            {data.high_token_share != null &&
              `, ${percent(data.high_token_share)} of their tokens`}
            .
          </Headline>
          <div className="space-y-1.5">
            {data.levels.map((level) => (
              <Row
                key={level.effort}
                label={level.effort}
                value={plural(level.sessions, 'session')}
              />
            ))}
          </div>
        </>
      )}
    </Card>
  )
}

function ModelNamesCard({
  data,
}: {
  data: SpendPatternsResponse['model_names']
}) {
  return (
    <Card title="Model names" icon={Tag}>
      {!data ? (
        <Unavailable />
      ) : data.sessions === 0 ? (
        <Headline>Every session names a real model.</Headline>
      ) : (
        <>
          <Headline warn>
            {count(data.sessions)} sessions don't say which model ran, so they
            can't be priced exactly.
          </Headline>
          <div className="space-y-1.5">
            {data.names.map((n) => (
              <Row
                key={n.model}
                label={`${n.model} (${n.kind})`}
                value={count(n.sessions)}
              />
            ))}
          </div>
        </>
      )}
    </Card>
  )
}

function EmptySessionsCard({
  data,
}: {
  data: SpendPatternsResponse['empty_sessions']
}) {
  return (
    <Card title="Empty sessions" icon={Inbox}>
      {!data ? (
        <Unavailable />
      ) : data.sessions === 0 ? (
        <Headline>No sessions ended with nothing in them.</Headline>
      ) : (
        <>
          <Headline warn>
            {count(data.sessions)} sessions ended with no events and no calls.
          </Headline>
          <div className="space-y-1.5">
            {data.by_source.map((s) => (
              <Row
                key={`${s.project}-${s.source}`}
                label={`${s.project} · ${s.source}`}
                value={count(s.sessions)}
              />
            ))}
          </div>
        </>
      )}
    </Card>
  )
}

function RepeatedCallsCard({
  data,
}: {
  data: SpendPatternsResponse['repeated_calls']
}) {
  return (
    <Card title="Repeated calls" icon={Copy}>
      {!data ? (
        <Unavailable />
      ) : data.repeats === 0 ? (
        <Headline>No call repeated the same input.</Headline>
      ) : (
        <>
          <Headline warn>
            {count(data.repeats)} calls sent the same input again within{' '}
            {data.window_minutes} minutes.
          </Headline>
          <div className="space-y-1.5">
            {data.by_caller.map((c) => (
              <Row
                key={`${c.project}-${c.source}`}
                label={
                  c.source === c.project
                    ? c.project
                    : `${c.project} · ${c.source}`
                }
                value={count(c.repeats)}
              />
            ))}
          </div>
        </>
      )}
    </Card>
  )
}

function GatedCard({
  data,
}: {
  data: SpendPatternsResponse['gated_automations']
}) {
  return (
    <Card title="Blocked automations" icon={Ban}>
      {!data ? (
        <Unavailable />
      ) : data.gated.length === 0 ? (
        <Headline>
          All {count(data.enabled)} turned-on automations can run.
        </Headline>
      ) : (
        <>
          <Headline warn>
            {data.gated.length} of {count(data.enabled)} turned-on automations
            can't run.
          </Headline>
          <ul className="space-y-2 text-sm">
            {data.gated.map((g) => (
              <li key={`${g.project}-${g.label}`}>
                <span className="text-slate-200">{g.label}</span>
                <span className="text-slate-500"> · {g.project}</span>
                <p className="text-xs text-slate-400">
                  {g.reasons.map(gateReason).join(', ')}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  )
}

function SpikeCard({
  data,
  days,
}: {
  data: SpendPatternsResponse['weekly_spike']
  days: number
}) {
  const show = (v: number) =>
    data?.measure === 'cash'
      ? formatCurrency(v)
      : `${count(Math.round(v))} tokens`
  return (
    <Card title="Compared with usual" icon={TrendingUp}>
      {!data ? (
        <Unavailable />
      ) : (
        <>
          <Headline warn={data.spike}>
            {data.ratio == null
              ? 'Not enough history to compare yet.'
              : data.spike
                ? `Spend is ${data.ratio}x the usual for ${days} days.`
                : `Spend is in line with usual (${data.ratio}x).`}
          </Headline>
          <div className="space-y-1.5">
            <Row label={`Last ${days} days`} value={show(data.current)} />
            <Row label="Usual (median of 4 before)" value={show(data.usual)} />
          </div>
        </>
      )}
    </Card>
  )
}

export function SpendPatternsSection({ daysRange }: { daysRange: number }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['spend-patterns', daysRange],
    queryFn: () => fetchSpendPatterns(daysRange),
    refetchInterval: 5 * 60 * 1000,
  })

  return (
    <div
      id="spend-patterns"
      className="panel-surface col-span-12 scroll-mt-4 p-5 lg:p-6"
    >
      <div className="mb-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
          Spend patterns
        </p>
        <p className="mt-1 text-sm text-slate-300">
          Where calls cost more than they should, or can't be priced.
        </p>
      </div>
      {isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-40 animate-pulse rounded-2xl bg-slate-800/60"
            />
          ))}
        </div>
      ) : error || !data ? (
        <p className="text-sm text-red-400">
          Spend patterns unavailable:{' '}
          {error instanceof Error ? error.message : 'no data'}
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <SpikeCard data={data.weekly_spike} days={data.window_days} />
          <UnpricedCard data={data.unpriced} />
          <ModelNamesCard data={data.model_names} />
          <EffortCard data={data.effort} />
          <RepeatedCallsCard data={data.repeated_calls} />
          <EmptySessionsCard data={data.empty_sessions} />
          <GatedCard data={data.gated_automations} />
        </div>
      )}
    </div>
  )
}
