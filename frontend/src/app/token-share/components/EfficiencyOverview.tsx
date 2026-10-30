'use client'

import Link from 'next/link'
import { useState } from 'react'
import { Cell, Pie, PieChart } from 'recharts'
import {
  type ActivityComparison,
  type ActivityCost,
  activitySessionsHref,
} from '@/lib/api/activity-cost'
import { type ContextSplit, contextTokens } from '@/lib/api/context-split'
import { durationPercent, durationSeconds } from '@/lib/api/duration-split'

export function EfficiencyOverview({
  activity,
  scope,
}: {
  activity: ActivityCost
  scope: URLSearchParams
}) {
  const [comparison, setComparison] = useState<
    'projects' | 'roles' | 'harnesses'
  >('projects')
  const split = activity.context_split
  if (!split)
    return (
      <p className="section-copy">
        Admin/Other comparisons are unavailable from this server.
      </p>
    )
  const groups =
    comparison === 'projects'
      ? activity.by_project
      : comparison === 'roles'
        ? activity.by_work_role
        : activity.by_harness
  const link = (row: ActivityComparison) => {
    const params = new URLSearchParams(scope)
    params.set('sort', 'admin_share')
    params.delete('sel')
    if ('project_id' in row) params.set('project', String(row.project_id))
    if ('work_role_id' in row) params.set('work_role', String(row.work_role_id))
    if ('harness_id' in row) params.set('harness', String(row.harness_id))
    return activitySessionsHref(undefined, undefined, params)
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-col items-stretch gap-x-8 gap-y-3 rounded-lg border border-slate-800 bg-slate-950/60 p-4 sm:flex-row sm:items-center">
        {split.denominator_tokens_estimate > 0 ? (
          <div aria-hidden="true" className="shrink-0 self-center">
            <PieChart width={176} height={156}>
              <Pie
                data={[
                  { name: 'Admin', value: split.admin_tokens_estimate },
                  { name: 'Other', value: split.other_tokens_estimate },
                ]}
                dataKey="value"
                innerRadius={48}
                outerRadius={70}
                stroke="none"
                isAnimationActive={false}
              >
                <Cell fill="#fbbf24" />
                <Cell fill="#64748b" />
              </Pie>
            </PieChart>
          </div>
        ) : null}
        <div className="min-w-0 flex-1 space-y-2">
          <h3 className="text-sm font-semibold text-slate-100">
            Estimated tool context
          </h3>
          <dl className="flex flex-wrap gap-x-8 gap-y-3">
            <div>
              <dt className="text-sm text-amber-300">Admin</dt>
              <dd className="text-3xl font-semibold tabular-nums text-slate-100">
                {durationPercent(split.admin_share)}
              </dd>
              <dd className="text-xs text-slate-400">
                {contextTokens(split.admin_tokens_estimate)}
              </dd>
            </div>
            <div>
              <dt className="text-sm text-slate-300">Other</dt>
              <dd className="text-3xl font-semibold tabular-nums text-slate-100">
                {durationPercent(split.other_share)}
              </dd>
              <dd className="text-xs text-slate-400">
                {contextTokens(split.other_tokens_estimate)}
              </dd>
            </div>
          </dl>
          <p className="section-copy">
            Tool text added once:{' '}
            {contextTokens(split.denominator_tokens_estimate)} ·{' '}
            {activity.sessions.toLocaleString()} sessions. Other includes
            substantive + unknown. Admin includes necessary support.
          </p>
          <p className="text-xs text-slate-400">
            Unknown {durationPercent(split.unknown_share)} · retained text on{' '}
            {split.tools_sampled - split.tools_missing_output}/
            {split.tools_sampled} calls
            {split.events_truncated
              ? ' · Capped sample: incomplete coverage'
              : ''}
            . Provider usage: {activity.tokens.denominator.toLocaleString()}{' '}
            recorded tokens; {activity.missing_usage_sessions} sessions without
            usage. Missing or truncated output has unknown size. Resident
            context is unavailable in this view.
          </p>
          {split.denominator_tokens_estimate === 0 && (
            <p className="section-copy">
              No retained tool text. Context shares are unavailable.
            </p>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-100">
          Compare estimated tool context
        </h3>
        <div className="flex flex-wrap gap-1" aria-label="Comparison groups">
          {(
            [
              ['projects', 'Projects'],
              ['roles', 'Work roles'],
              ['harnesses', 'Harnesses'],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={comparison === value}
              onClick={() => setComparison(value)}
              className={`rounded-md border px-3 py-1.5 text-xs focus-ring-amber ${comparison === value ? 'border-amber-500/50 bg-amber-500/10 text-amber-200' : 'border-slate-700 text-slate-300'}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <p className="section-copy">
        Shares use each group’s total estimated tool tokens, weighted by text
        size. Same interval and filters. Lower admin share alone does not
        establish better results.
      </p>
      {!groups ? (
        <p className="section-copy">
          This comparison is unavailable from this server.
        </p>
      ) : groups.length === 0 ? (
        <p className="section-copy">
          No sessions match this interval and filters.
        </p>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {groups.map((row) => (
            <ComparisonRow
              key={
                'project_id' in row
                  ? String(row.project_id)
                  : 'work_role_id' in row
                    ? String(row.work_role_id)
                    : String(row.harness_id)
              }
              row={row}
              href={link(row)}
            />
          ))}
        </div>
      )}
      <p className="text-xs text-slate-400">
        Arguments use a reference tokenizer within the recorded budget; returned
        text uses a character estimate. Each call counts once. Prose, system
        instructions, images, protocol framing, repeated context reads and
        compaction are excluded. Missing output has unknown size. These
        estimates do not allocate provider tokens or cost.
      </p>
    </div>
  )
}

function ComparisonRow({
  row,
  href,
}: {
  row: ActivityComparison
  href: string
}) {
  const split = row.context_split
  if (!split)
    return (
      <p className="section-copy">
        {row.label}: estimated tool context unavailable.
      </p>
    )
  return (
    <div className="min-w-0 rounded-lg border border-slate-800 p-3 space-y-2">
      <div className="flex flex-wrap justify-between gap-x-3 gap-y-1 text-sm">
        <Link
          href={href}
          className="min-w-0 break-words text-amber-300 underline focus-ring-amber"
        >
          {row.label}
        </Link>
        <span className="text-xs text-slate-400">
          {row.sessions.toLocaleString()}{' '}
          {row.sessions === 1 ? 'session' : 'sessions'} ·{' '}
          {contextTokens(split.denominator_tokens_estimate)}
        </span>
      </div>
      <SplitBar split={split} />
      <p className="text-xs text-slate-300 tabular-nums">
        Admin {durationPercent(split.admin_share)} · Other{' '}
        {durationPercent(split.other_share)}
      </p>
      <details className="text-xs text-slate-400">
        <summary className="cursor-pointer focus-ring-amber">
          Coverage and recorded usage
        </summary>
        <div className="mt-2 space-y-2">
          <p>
            Unknown {durationPercent(split.unknown_share)} (
            {contextTokens(split.unknown_tokens_estimate)}) · retained text on{' '}
            {split.tools_sampled - split.tools_missing_output}/
            {split.tools_sampled} calls
            {split.events_truncated
              ? ' · Capped sample: incomplete coverage.'
              : '.'}{' '}
            Retained text can be a capped or redacted summary and undercount
            model-seen output. Missing output has unknown size. Arguments
            tokenized on {split.tokenized_argument_calls}/{split.tools_sampled}{' '}
            calls; {split.estimated_argument_calls} use a character estimate.
            Returned text: {split.output_characters_per_token} characters per
            estimated token. Tool time:{' '}
            {durationSeconds(row.duration_split.admin_seconds)} admin /{' '}
            {durationSeconds(row.duration_split.denominator_seconds)} recorded.
          </p>
          {row.usage && row.coverage?.usage_sessions !== 0 ? (
            <p>
              Recorded input {row.usage.input_tokens.toLocaleString()} · output{' '}
              {row.usage.output_tokens.toLocaleString()}.{' '}
              {row.usage.cache_detail_input_tokens === 0 &&
              row.usage.input_tokens > 0
                ? 'Cache read/write unavailable. '
                : `Input includes cache read ${row.usage.cache_read_tokens.toLocaleString()} + write ${row.usage.cache_write_tokens.toLocaleString()}. `}
              Cache detail covers{' '}
              {row.usage.cache_detail_input_tokens.toLocaleString()}/
              {row.usage.input_tokens.toLocaleString()} input tokens.{' '}
              {row.coverage?.missing_usage_sessions ?? 'Unknown'} sessions
              without usage.
              {row.usage.cache_detail_input_tokens < row.usage.input_tokens &&
                ' Uncovered cache split is unknown.'}
            </p>
          ) : (
            <p>Recorded token partitions unavailable.</p>
          )}
          {row.cost ? (
            <p>
              API-equivalent value: {money(row.cost.api_equiv_usd)} (
              {row.cost.api_equiv_known_calls}/{row.cost.recorded_calls} calls
              priced). Cash cost: {money(row.cost.cash_usd)} (
              {row.cost.cash_known_calls}/{row.cost.recorded_calls} calls).
              Missing prices remain unknown. API-equivalent value is separate
              from cash spend.
            </p>
          ) : (
            <p>Recorded cost unavailable.</p>
          )}
        </div>
      </details>
    </div>
  )
}

function SplitBar({ split }: { split: ContextSplit }) {
  return (
    <div
      aria-hidden="true"
      className="flex h-2 overflow-hidden rounded bg-slate-800"
    >
      {split.admin_share !== null && (
        <>
          <div
            className="bg-amber-400"
            style={{ width: `${split.admin_share * 100}%` }}
          />
          <div
            className="bg-slate-500"
            style={{ width: `${(split.other_share ?? 0) * 100}%` }}
          />
        </>
      )}
    </div>
  )
}

function money(value: number | null) {
  return value === null
    ? 'Unavailable'
    : new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: 4,
      }).format(value)
}
