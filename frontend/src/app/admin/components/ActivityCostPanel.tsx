'use client'

import Link from 'next/link'
import {
  type ActivityCategory,
  type ActivityCost,
  activitySessionsHref,
} from '@/lib/api/activity-cost'
import { ActivityAccounting } from './ActivityAccounting'

const LABELS: Record<ActivityCategory, string> = {
  substantive: 'Substantive',
  administration: 'Admin + support',
  unknown: 'Unknown + mixed',
}

export function activitySeconds(value: number): string {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}s`
}

export function ActivityCostPanel({
  activity,
  isLoading,
  error,
  onRetry,
}: {
  activity: ActivityCost | null
  isLoading: boolean
  error: string | null
  onRetry: () => void
}) {
  return (
    <section
      id="activity"
      aria-labelledby="activity-heading"
      className="section-card space-y-4 scroll-mt-16"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="activity-heading" className="section-heading">
            Work and admin activity
          </h2>
          <p className="section-copy mt-1">
            Across all Hub projects and providers · last 24 hours
          </p>
        </div>
        <Link href={activitySessionsHref()} className="button-secondary">
          Browse sessions
        </Link>
      </div>
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-amber-800 bg-amber-950/20 p-3 text-sm text-amber-200"
        >
          <p>
            {activity
              ? 'Refresh failed. Showing the last loaded snapshot.'
              : 'Activity could not be loaded.'}{' '}
            {error}
          </p>
          <button
            type="button"
            className="button-secondary mt-2"
            onClick={onRetry}
          >
            Retry activity
          </button>
        </div>
      )}
      {isLoading && !activity ? (
        <p role="status" className="section-copy">
          Loading activity…
        </p>
      ) : !activity ? (
        !error && (
          <p className="section-copy">
            Activity data is unavailable from this server.
          </p>
        )
      ) : (
        <>
          <ActivityAccounting activity={activity} />
          <h3 className="text-sm font-semibold text-slate-100">
            Observed tool time
          </h3>
          <p className="text-sm text-slate-300">
            Measured tool time:{' '}
            <strong>
              {activitySeconds(activity.tool_time.denominator_seconds)}
            </strong>{' '}
            across {activity.sessions.toLocaleString()} sessions. Intervals are
            merged within each session; concurrent sessions add. Wait-only time
            is excluded.
          </p>
          {activity.tool_time.denominator_seconds === 0 ? (
            <p className="section-copy">
              No measured tool-runtime intervals in this window. Shares are
              unavailable.
            </p>
          ) : (
            <dl className="grid gap-3 sm:grid-cols-3">
              {activity.tool_time.breakdown.map((row) => (
                <div
                  key={row.category}
                  className="rounded-lg border border-slate-800 bg-slate-950/60 p-4"
                >
                  <dt className="text-sm text-slate-300">
                    {LABELS[row.category]}
                  </dt>
                  <dd className="mt-2 text-2xl font-semibold text-slate-100 tabular-nums">
                    {row.share === null
                      ? 'Unavailable'
                      : `${(row.share * 100).toFixed(1)}%`}
                  </dd>
                  <dd className="mt-1 text-xs text-slate-400">
                    {activitySeconds(row.seconds)} /{' '}
                    {activitySeconds(activity.tool_time.denominator_seconds)}
                  </dd>
                </div>
              ))}
            </dl>
          )}
          <p className="section-copy">
            Repetition alone does not show waste. Thinking, idle time and
            unrecorded work are unmeasured; these are tool-time shares, not
            token, spend or total-work shares.
          </p>
          <div className="rounded-lg border border-slate-700 bg-slate-950/60 p-4 text-sm text-slate-300 space-y-2">
            <h3 className="font-semibold text-slate-100">Coverage and gaps</h3>
            <p>
              {activity.events_sampled.toLocaleString()} events sampled · cap{' '}
              {activity.event_limit.toLocaleString()} ·{' '}
              {activity.events_truncated
                ? 'CAPPED: recent events only; earlier activity may be omitted.'
                : 'Event cap not reached.'}
            </p>
            <p>
              {activity.tools_missing_duration.toLocaleString()} /{' '}
              {activity.tools_sampled.toLocaleString()} observed tool calls lack
              usable duration. Missing time has unknown size. Excluded wait-only
              time: {activitySeconds(activity.tool_time.explicit_wait_seconds)}.
              Mixed time within unknown:{' '}
              {activitySeconds(activity.tool_time.mixed_seconds)}.
            </p>
            <p>
              {activity.unlinked_sessions.toLocaleString()} /{' '}
              {activity.sessions.toLocaleString()} sessions have no single
              reliable task link:{' '}
              {activitySeconds(activity.unlinked_tool_seconds)} measured tool
              time and {activity.unlinked_tokens.toLocaleString()} recorded
              tokens remain unlinked, including accounting without a Hub
              session.
            </p>
            <p>
              {activity.missing_usage_sessions.toLocaleString()} /{' '}
              {activity.sessions.toLocaleString()} sessions lack usage.{' '}
              {activity.tokens.denominator.toLocaleString()} tokens recorded
              using one source per session; this is not a reconciled billing
              total. No per-command token allocation is available.
            </p>
            <p className="text-xs text-slate-400">
              Window: {new Date(activity.window_start).toLocaleString()} –{' '}
              {new Date(activity.window_end).toLocaleString()}. Tool interval
              placement may be approximate.
            </p>
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            <div className="min-w-0 space-y-3">
              <h3 className="text-sm font-semibold text-slate-100">
                Repeated admin and support families
              </h3>
              <p className="section-copy">
                Showing {activity.repeat_admin_patterns.length} of{' '}
                {activity.repeat_admin_patterns_total} families, ranked by
                measured tool time. Family times can overlap; do not add them.
                Open a recorded session to judge whether repetition was needed.
              </p>
              {activity.repeat_admin_patterns.length === 0 && (
                <p className="section-copy">
                  No repeated admin families observed in the sampled events.
                </p>
              )}
              {activity.repeat_admin_patterns.map((row) => (
                <div
                  key={row.family}
                  className="rounded-lg border border-slate-800 bg-slate-950/60 p-4 space-y-2"
                >
                  <p className="text-sm font-medium text-slate-100 break-words">
                    {row.family}
                  </p>
                  <p className="text-xs text-slate-300">
                    {row.calls.toLocaleString()} calls ·{' '}
                    {row.sessions.toLocaleString()} sessions ·{' '}
                    {activitySeconds(row.measured_tool_seconds)}
                  </p>
                  <p className="text-xs text-slate-400">
                    Projects shown: {row.projects.length} / {row.projects_total}
                  </p>
                  {row.projects.map((project) => (
                    <div key={project.project_id} className="text-xs space-y-1">
                      <p className="text-slate-300 break-words">
                        {project.project_id} · {project.calls.toLocaleString()}{' '}
                        calls · {activitySeconds(project.measured_tool_seconds)}
                      </p>
                      <div className="flex flex-wrap gap-x-4 gap-y-2">
                        <Link
                          href={activitySessionsHref(
                            project.project_id,
                            project.sample_session_id,
                          )}
                          className="text-amber-300 underline focus-ring-amber"
                        >
                          Open {row.family} session in {project.project_id}
                        </Link>
                        <Link
                          href={activitySessionsHref(project.project_id)}
                          className="text-slate-300 underline focus-ring-amber"
                        >
                          All {project.project_id} sessions
                        </Link>
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
            <div className="min-w-0 space-y-3">
              <h3 className="text-sm font-semibold text-slate-100">
                Reliably linked tasks
              </h3>
              <p className="section-copy">
                Showing {activity.task_rollups.length} of{' '}
                {activity.task_rollups_total} tasks, ranked by recorded tokens.
                Only sessions with one durable project/task binding qualify.
                Session totals do not prove all work served that task.
              </p>
              {activity.task_rollups.length === 0 && (
                <p className="section-copy">
                  No unambiguous task links in this window. Use the project
                  sessions above; task attribution remains unknown.
                </p>
              )}
              {activity.task_rollups.map((row) => (
                <div
                  key={`${row.project_id}/${row.task_id}`}
                  className="rounded-lg border border-slate-800 bg-slate-950/60 p-4 space-y-2 text-xs"
                >
                  <p className="text-sm text-slate-100 break-words">
                    {row.project_id} · {row.task_id}
                  </p>
                  <p className="text-slate-300">
                    {row.sessions.toLocaleString()} linked sessions (
                    {row.missing_usage_sessions.toLocaleString()} without usage)
                    · {activitySeconds(row.tool_time.denominator_seconds)}{' '}
                    measured tool time · {row.tokens.toLocaleString()} recorded
                    tokens ·{' '}
                    {row.transcript.breakdown
                      .find((part) => part.category === 'administration')
                      ?.characters.toLocaleString()}{' '}
                    admin transcript characters
                  </p>
                  <Link
                    href={activitySessionsHref(
                      row.project_id,
                      row.sample_session_id,
                    )}
                    className="inline-block text-amber-300 underline focus-ring-amber"
                  >
                    Open a linked session for {row.task_id}
                  </Link>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </section>
  )
}
