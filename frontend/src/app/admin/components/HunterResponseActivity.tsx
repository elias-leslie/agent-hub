'use client'

import Link from 'next/link'
import {
  type ActivityCost,
  activitySessionsHref,
  type HunterResponseCategory,
} from '@/lib/api/activity-cost'

const LABELS: Record<HunterResponseCategory, string> = {
  investigation_only: 'Investigation only',
  mixed: 'Mixed',
  support_coordination: 'Support / coordination',
  unknown: 'Unknown',
}
const ACTIONS = {
  source_read: 'Source read',
  source_search: 'Source search',
  recon_run: 'Recon call',
}
const percent = (value: number | null) =>
  value === null ? 'Unavailable' : `${(value * 100).toFixed(1)}%`
const count = (value: number | null) =>
  value === null ? 'Unavailable' : value.toLocaleString()

export function HunterResponseActivity({
  activity,
  scope,
}: {
  activity: ActivityCost
  scope?: URLSearchParams
}) {
  const data = activity.hunter_responses
  return (
    <details className="rounded-lg border border-slate-700 p-3">
      <summary className="cursor-pointer text-sm text-slate-200 focus-ring-amber">
        Neri hunter responses
        {data &&
          ` · ${count(data.responses)} responses · ${count(data.sessions_total)} ${data.sessions_total === 1 ? 'session' : 'sessions'}`}
      </summary>
      <div className="mt-3 space-y-3 text-sm text-slate-300">
        {!data ? (
          <p>Response accounting is unavailable from this server.</p>
        ) : data.sessions_total === 0 ? (
          <p>No declared Neri hunting or recon sessions in this window.</p>
        ) : (
          <>
            <p className="section-copy">
              Unique provider responses for declared Neri hunting and recon
              sessions. Categories describe linked tool calls. Source reads,
              searches and recon calls show observed investigation; they do not
              establish a bug, successful execution or the purpose of every
              token. Mixed responses stay whole.
            </p>
            {data.events_truncated && (
              <p className="text-amber-200">
                Event sample capped. Response categories are unknown; counts and
                first observations cover the retained sample only.
              </p>
            )}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs tabular-nums">
                <caption className="sr-only">
                  Neri response and reported token shares by observed activity
                </caption>
                <thead className="text-slate-400">
                  <tr>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Observed activity
                    </th>
                    <th scope="col" className="py-2 pr-4 font-medium">
                      Responses / share
                    </th>
                    <th scope="col" className="py-2 font-medium">
                      Input + output / share
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.breakdown.map((part) => (
                    <tr
                      key={part.category}
                      className="border-t border-slate-800"
                    >
                      <th scope="row" className="py-2 pr-4 font-normal">
                        {LABELS[part.category]}
                      </th>
                      <td className="py-2 pr-4">
                        {count(part.responses)} · {percent(part.response_share)}
                      </td>
                      <td className="py-2">
                        {count(part.tokens)} · {percent(part.token_share)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="section-copy">
              Cumulative reported input {count(data.usage.input_tokens)} ·
              output {count(data.usage.output_tokens)}. Input includes recorded
              cache read {count(data.usage.cache_read_tokens)} and write{' '}
              {count(data.usage.cache_write_tokens)}; cache detail covers{' '}
              {count(data.usage.cache_detail_input_tokens)} input tokens.
              Repeated input adds across responses. These totals overlap other
              usage on this page.
            </p>
            <p className="section-copy">
              {count(data.tools_without_response)} calls lack a response link ·{' '}
              {count(data.sessions_without_usage)} sessions lack usable response
              usage · {count(data.duplicate_usage_events)} duplicate usage
              events excluded · {count(data.unusable_usage_events)} unusable
              usage events. Unsupported actions stay unknown.
            </p>
            <p className="section-copy">
              Showing {data.rows.length} of {data.sessions_total} sessions,
              ranked by reported response tokens. Response numbers are within
              this window's sample; earlier investigation may be absent.
            </p>
            {data.rows.map((row) => {
              const first = row.first_observed_investigation
              return (
                <div
                  key={row.session_id}
                  className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 space-y-1 text-xs"
                >
                  <p className="break-words">
                    <Link
                      href={activitySessionsHref(
                        row.project_id,
                        row.session_id,
                        scope,
                      )}
                      className="text-amber-300 underline focus-ring-amber"
                    >
                      {row.session_id}
                    </Link>{' '}
                    · {row.harness} · {row.work_role} · {count(row.responses)}{' '}
                    responses
                  </p>
                  <p>
                    Input per response: first{' '}
                    {count(row.input_per_response.first_tokens)} → peak{' '}
                    {count(row.input_per_response.peak_tokens)} tokens at
                    sampled response{' '}
                    {count(row.input_per_response.peak_sample_response_number)}.
                    This is separate from cumulative repeated input.
                  </p>
                  <p>
                    {first ? (
                      <>
                        First observed investigation: {ACTIONS[first.action]} ·
                        sampled response {count(first.sample_response_number)} ·{' '}
                        {first.seconds_from_first_response === null
                          ? 'elapsed time unavailable'
                          : `${first.seconds_from_first_response.toLocaleString()}s since first sampled response`}{' '}
                        · input {count(first.input_tokens)} tokens.
                      </>
                    ) : (
                      'No investigation call observed in this sample.'
                    )}{' '}
                    {row.window_starts_mid_session &&
                      'This window starts after the session began.'}
                  </p>
                  <p>
                    {row.breakdown
                      .map(
                        (part) =>
                          `${LABELS[part.category]}: ${count(part.responses)} response${part.responses === 1 ? '' : 's'} / ${percent(part.token_share)} tokens`,
                      )
                      .join(' · ')}
                  </p>
                </div>
              )
            })}
            <details>
              <summary className="cursor-pointer text-xs text-slate-400 focus-ring-amber">
                Response accounting limits
              </summary>
              <p className="mt-2 section-copy">{data.basis}</p>
            </details>
          </>
        )}
      </div>
    </details>
  )
}
