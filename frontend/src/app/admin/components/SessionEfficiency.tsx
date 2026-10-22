'use client'

import Link from 'next/link'
import {
  type ActivityCost,
  activitySessionParams,
  activitySessionsHref,
  type EfficiencyStatus,
} from '@/lib/api/activity-cost'

const STATUS: Record<EfficiencyStatus, string> = {
  within_goal: 'Observed admin share within target',
  above_goal: 'Observed admin share above target',
  insufficient_coverage: 'Limited coverage for admin share',
  unmeasured: 'No measured tool time',
  goal_not_selected: 'Admin target unset',
}
const percent = (value: number | null) =>
  value === null ? 'Unavailable' : `${(value * 100).toFixed(1)}%`
const seconds = (value: number) =>
  `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}s`

export function SessionEfficiency({
  activity,
  sessionParams,
}: {
  activity: ActivityCost
  sessionParams?: URLSearchParams
}) {
  const scope = activitySessionParams(activity, sessionParams)
  const data = activity.session_efficiency
  if (!data)
    return (
      <p className="section-copy">
        Session efficiency is unavailable from this server.
      </p>
    )
  return (
    <div className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-100">
        Session efficiency
      </h3>
      <p className="text-sm text-slate-300">
        Local trial goal: at least{' '}
        {percent(data.trial_goal.relative_cost_reduction_target)} lower full
        API-equivalent cost per accepted outcome, with acceptance criteria and
        checks unchanged. Matched local trials found lower costs for Pi in
        qualified runs, but the full experiment did not meet this goal after
        optimization costs. These tool-time shares do not establish cost savings
        or token purpose.
      </p>
      <p className="section-copy">
        {data.goal.admin_share_target === null
          ? 'Admin-share target is unset.'
          : `Review target: admin + support ≤ ${percent(data.goal.admin_share_target)} of measured non-wait tool time.`}{' '}
        Substantive tool work is a productive-work signal; completion and tool
        class do not prove a useful outcome. Admin + support includes necessary
        work; avoidability needs session review.
      </p>
      <p className="section-copy">
        Admin-share assessment, if a target is selected, requires an uncapped
        sample, duration on at least{' '}
        {percent(data.goal.minimum_duration_coverage)} of calls and at most{' '}
        {percent(data.goal.maximum_unknown_share)} unknown/mixed time. Missing
        time still has unknown size. {data.status_counts.within_goal} within
        admin target · {data.status_counts.above_goal} above admin target ·{' '}
        {data.status_counts.insufficient_coverage} limited coverage ·{' '}
        {data.status_counts.unmeasured} unmeasured ·{' '}
        {data.status_counts.goal_not_selected} awaiting admin target.
      </p>
      <p className="section-copy">
        Showing {data.rows.length} of {data.sessions_total} sessions, ranked by
        estimated admin tool-context tokens. Compare equal windows with the same
        project, provider, model and method; check coverage before calling a
        change a regression.
      </p>
      {data.rows.length === 0 && (
        <p className="section-copy">No sessions in this window.</p>
      )}
      {data.rows.map((row) => (
        <details
          key={row.session_id}
          className="rounded-lg border border-slate-800 bg-slate-950/60 p-3"
        >
          <summary className="cursor-pointer text-sm text-slate-100 focus-ring-amber break-words">
            {row.project_id} · {row.session_id} · Estimated tool context: Admin{' '}
            {percent(row.context_split?.admin_share ?? null)} · Other{' '}
            {percent(row.context_split?.other_share ?? null)} ·{' '}
            {row.context_split?.denominator_tokens_estimate.toLocaleString() ??
              'Unavailable'}{' '}
            est. tokens
          </summary>
          <div className="mt-3 space-y-2 text-xs text-slate-300">
            <p>
              Unknown {percent(row.context_split?.unknown_share ?? null)}{' '}
              included in Other. Retained output on{' '}
              {row.context_split
                ? `${row.context_split.tools_sampled - row.context_split.tools_missing_output}/${row.context_split.tools_sampled}`
                : 'Unavailable'}{' '}
              calls. Tool-time assessment: {STATUS[row.goal_status]} ·{' '}
              {seconds(row.tool_time.denominator_seconds)} measured.
            </p>
            <p>
              {row.provider} · Stored model: {row.model ?? 'Unavailable'} ·{' '}
              {row.usage_source === 'missing'
                ? 'Provider usage unavailable'
                : `${row.tokens.toLocaleString()} recorded provider tokens`}
            </p>
            {row.usage_source === 'missing' ? (
              <p>Provider token partitions unavailable.</p>
            ) : (
              <p>
                Input {row.usage.input_tokens.toLocaleString()} · output{' '}
                {row.usage.output_tokens.toLocaleString()} tokens. Input
                includes cache.{' '}
                {row.usage.cache_detail_input_tokens === 0 &&
                row.usage.input_tokens > 0 ? (
                  'Cache read/write unavailable. '
                ) : (
                  <>
                    Recorded cache read{' '}
                    {row.usage.cache_read_tokens.toLocaleString()} · cache write{' '}
                    {row.usage.cache_write_tokens.toLocaleString()} tokens.{' '}
                  </>
                )}
                Cache detail covers{' '}
                {row.usage.cache_detail_input_tokens.toLocaleString()} /{' '}
                {row.usage.input_tokens.toLocaleString()} input tokens.
                {row.usage.cache_detail_input_tokens < row.usage.input_tokens &&
                  ' Uncovered input has an unknown cache split.'}
              </p>
            )}
            <p>
              The stored session model can be unknown or change; it does not
              establish the served model for each call.
            </p>
            <p>
              {row.tool_time.breakdown
                .map(
                  (part) =>
                    `${part.category === 'administration' ? 'Admin + support' : part.category === 'unknown' ? 'Unknown + mixed' : 'Substantive'}: ${percent(part.share)} (${seconds(part.seconds)})`,
                )
                .join(' · ')}{' '}
              / {seconds(row.tool_time.denominator_seconds)} measured non-wait
              tool time.
            </p>
            <p>
              {row.tools_sampled - row.tools_missing_duration} /{' '}
              {row.tools_sampled} calls have duration ·{' '}
              {seconds(row.tool_time.explicit_wait_seconds)} wait-only occupancy
              excluded · Sampled event span:{' '}
              {row.sampled_event_span_seconds === null
                ? 'Unavailable'
                : seconds(row.sampled_event_span_seconds)}
              . The span includes gaps; thinking, idle time and full session
              elapsed time remain unknown.
            </p>
            <p>
              {row.transcript.breakdown
                .find((part) => part.category === 'administration')
                ?.characters.toLocaleString()}{' '}
              admin + support characters /{' '}
              {row.transcript.characters.toLocaleString()} sampled tool
              characters · {row.transcript.calls_with_returned_text} /{' '}
              {row.transcript.calls_with_returned_text +
                row.transcript.calls_missing_returned_text}{' '}
              calls have returned text. Text footprint is separate from provider
              tokens; causal admin token spend is unknown.
            </p>
            <p>
              Repeated admin families: {row.repeat_admin_patterns.length} /{' '}
              {row.repeat_admin_patterns_total}. Family times can overlap.
            </p>
            {row.repeat_admin_patterns.length === 0 && (
              <p>No repeated admin families in this sample.</p>
            )}
            {row.repeat_admin_patterns.map((family) => (
              <p key={family.family}>
                {family.family}: {family.calls} calls ·{' '}
                {seconds(family.measured_tool_seconds)}
              </p>
            ))}
            <Link
              href={activitySessionsHref(row.project_id, row.session_id, scope)}
              className="inline-block text-amber-300 underline focus-ring-amber"
            >
              Review session {row.session_id}
            </Link>
          </div>
        </details>
      ))}
      <details className="rounded-lg border border-slate-700 p-3">
        <summary className="cursor-pointer text-sm text-slate-100 focus-ring-amber">
          Lean session review routine
        </summary>
        <ol className="mt-3 list-decimal pl-5 space-y-2 text-sm text-slate-300">
          <li>
            At the start, check one comparable window and its coverage. Pick the
            largest repeated admin family to inspect.
          </li>
          <li>
            Read that session once. Keep necessary checks and coordination;
            simplify one demonstrated repeat, such as unchanged checks or
            repeated context discovery.
          </li>
          <li>
            At the end, compare the same window size, project, provider and
            model. Keep substantive time and coverage visible; lower admin share
            alone does not prove progress.
          </li>
          <li>
            Leave the result, session link and one next change in the existing
            work record or handoff. No per-command reporting or new form.
          </li>
        </ol>
      </details>
    </div>
  )
}
