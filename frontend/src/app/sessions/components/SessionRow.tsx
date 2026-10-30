import { memo } from 'react'
import { contextTokens } from '@/lib/api/context-split'
import {
  type AccountingWindow,
  durationPercent,
  durationSeconds,
} from '@/lib/api/duration-split'
import type { SessionListItem } from '@/lib/api/sessions'
import { cn } from '@/lib/utils'
import type { SortField } from '../types'
import {
  formatDurationMs,
  formatRelativeTime,
  getExecutionIdentity,
  getSessionLastActive,
  getSessionSourceLabel,
  getSessionTitle,
  getUsageSummary,
} from '../utils'
import { RequestErrorsBadge } from './RequestErrorsBadge'
import { StatusCell } from './StatusCell'

export type AdminSort = Extract<
  SortField,
  'admin_share' | 'admin_tokens' | 'admin_duration'
>

/** The admin accounting sort in effect, if any; its value gets a column while it orders the list. */
export function adminSortOf(sort: SortField): AdminSort | null {
  return sort === 'admin_share' ||
    sort === 'admin_tokens' ||
    sort === 'admin_duration'
    ? sort
    : null
}

const ADMIN_HEADER: Record<AdminSort, string> = {
  admin_share: 'Admin share',
  admin_tokens: 'Admin tokens',
  admin_duration: 'Admin time',
}

/** Column template shared by the header and rows so they always line up. */
export function sessionGridClass(adminSort: AdminSort | null = null) {
  // Title is the only flexible column; the admin column shows only while an admin sort orders the list.
  return adminSort
    ? 'xl:grid xl:grid-cols-[84px_minmax(10rem,1fr)_110px_140px_150px_112px_96px_64px_60px]'
    : 'xl:grid xl:grid-cols-[84px_minmax(10rem,1fr)_110px_140px_150px_112px_64px_60px]'
}

/** The sorted admin value; a dash where the server has no share (it sorts those rows last). */
function adminMetric(session: SessionListItem, sort: AdminSort): string {
  const accounting = session.activity_accounting
  const context = accounting?.context_split
  if (sort === 'admin_duration')
    return accounting?.admin_share == null
      ? '—'
      : durationSeconds(accounting.admin_seconds)
  if (context?.admin_share == null) return '—'
  return sort === 'admin_share'
    ? durationPercent(context.admin_share)
    : context.admin_tokens_estimate.toLocaleString()
}

/** Retained text is missing or the sample was capped, so the estimate is a lower bound. */
export function isPartialContext(session: SessionListItem): boolean {
  const context = session.activity_accounting?.context_split
  return Boolean(
    context && (context.tools_missing_output > 0 || context.events_truncated),
  )
}

export function accountingWindowText(
  window: AccountingWindow | null | undefined,
): string {
  return window
    ? `Accounting interval ${new Date(window.start).toLocaleString()} – ${new Date(window.end).toLocaleString()}.`
    : 'Accounting interval unavailable.'
}

export function adminMetricTitle(session: SessionListItem): string {
  const accounting = session.activity_accounting
  const context = accounting?.context_split
  if (!context) return 'Estimated tool context unavailable from this server.'
  return `${contextTokens(context.admin_tokens_estimate)} admin / ${contextTokens(context.denominator_tokens_estimate)} added tool text. Unknown ${durationPercent(context.unknown_share)} included in Other. Retained text on ${context.tools_sampled - context.tools_missing_output}/${context.tools_sampled} calls. Excludes prose, system instructions, repeated context reads and compaction. Resident context is unavailable here; provider usage is cumulative. Retained text may be a capped or redacted summary and undercount model-seen output. Missing output has unknown size.${context.events_truncated ? ' Capped sample.' : ''}${accounting ? ` Tool time: ${durationSeconds(accounting.admin_seconds)} admin / ${durationSeconds(accounting.denominator_seconds)} recorded.` : ''}`
}

function absolute(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export const SessionRow = memo(function SessionRow({
  session,
  isCursor,
  isSelected,
  adminSort = null,
  onClick,
}: {
  session: SessionListItem
  /** Keyboard cursor; carries the roving tabindex. */
  isCursor: boolean
  /** Row whose session is expanded beneath it. */
  isSelected: boolean
  /** Admin accounting sort in effect; adds its column. */
  adminSort?: AdminSort | null
  onClick: (id: string) => void
}) {
  const title = getSessionTitle(session)
  const shortId = session.id.slice(0, 8)
  const titleIsId = title === `session ${shortId}`
  const identity = getExecutionIdentity(session)
  const usage = getUsageSummary(session)
  const lastActive = getSessionLastActive(session)
  const durationMs =
    new Date(lastActive).getTime() - new Date(session.created_at).getTime()
  const source = getSessionSourceLabel(session)
  const agent = session.agent_slug?.trim() || null
  const children = session.child_session_count ?? 0
  const activeChildren = session.active_child_session_count ?? 0
  const modelTitle = identity.showRequested
    ? `requested ${identity.requestedModel} · ran ${identity.effectiveModel}`
    : identity.effectiveModel

  return (
    <div
      role="button"
      aria-expanded={isSelected}
      tabIndex={isCursor ? 0 : -1}
      data-session-id={session.id}
      data-testid="session-row"
      onClick={() => onClick(session.id)}
      className={cn(
        'cursor-pointer gap-2 border-b border-slate-800/50 px-3 py-2 text-[13px] outline-none transition-colors xl:min-h-10 xl:items-center',
        sessionGridClass(adminSort),
        isSelected
          ? 'bg-slate-800/60'
          : isCursor
            ? 'bg-slate-900/60'
            : 'hover:bg-slate-900/40',
        'focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber-400/60',
      )}
    >
      {/* Phone: line 1 is title + status */}
      <div className="flex min-w-0 items-center gap-2 xl:contents">
        <div className="order-2 flex shrink-0 items-center gap-2 xl:order-none xl:flex-col xl:items-start xl:gap-0.5">
          <StatusCell
            status={session.status}
            liveActivity={session.live_activity}
            showLabel
          />
          <RequestErrorsBadge errors={session.request_errors} />
        </div>
        <div className="order-1 flex min-w-0 flex-1 items-baseline gap-2 xl:order-none">
          <span className="truncate text-slate-100" title={title}>
            {title}
          </span>
          {titleIsId ? null : (
            <span className="hidden shrink-0 font-mono text-[11px] text-slate-500 sm:inline">
              {shortId}
            </span>
          )}
          {children > 0 ? (
            <span
              className="shrink-0 rounded border border-slate-700 px-1 text-[11px] text-slate-400"
              title={`${children} sub-agent${children === 1 ? '' : 's'}${activeChildren ? `, ${activeChildren} running` : ''}`}
            >
              {children} sub
              {activeChildren ? (
                <span className="text-emerald-300">
                  {' '}
                  · {activeChildren} running
                </span>
              ) : null}
            </span>
          ) : null}
        </div>
      </div>

      {/* Phone: line 2 is project · agent · tokens · last active */}
      <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 text-[12px] text-slate-400 xl:contents">
        <span className="truncate md:text-[13px] md:text-slate-300">
          {session.project_id}
        </span>
        <span
          className="truncate"
          title={agent ? `${agent} · ${source}` : source}
        >
          {agent ? (
            <>
              <span className="text-slate-300">{agent}</span>
              <span className="text-slate-400"> · {source}</span>
            </>
          ) : (
            source
          )}
        </span>
        <span
          className="hidden truncate font-mono text-[12px] text-slate-400 lg:block"
          title={modelTitle}
        >
          {identity.effectiveModel}
          {identity.fallbackUsed ? (
            <span className="ml-1 text-amber-300/80">fallback</span>
          ) : null}
        </span>
        <span
          className={cn(
            'whitespace-nowrap font-mono text-[12px] tabular-nums md:text-right',
            usage.known ? 'text-slate-300' : 'text-slate-500',
          )}
          title={usage.title}
        >
          {usage.label}
        </span>
        {adminSort ? (
          <span
            className="whitespace-nowrap font-mono text-[12px] tabular-nums text-slate-300 xl:text-right"
            title={adminMetricTitle(session)}
          >
            <span className="xl:hidden">admin </span>
            {adminMetric(session, adminSort)}
            {isPartialContext(session) ? (
              <span className="block text-[11px] text-slate-400">partial</span>
            ) : null}
          </span>
        ) : null}
        <span
          className="font-mono text-[12px] tabular-nums text-slate-400 md:text-right"
          title={`Last active ${absolute(lastActive)}`}
        >
          {formatRelativeTime(lastActive)}
        </span>
        <span
          className="hidden font-mono text-[12px] tabular-nums text-slate-500 md:text-right lg:block"
          title={`Started ${absolute(session.created_at)}`}
        >
          {formatDurationMs(durationMs)}
        </span>
      </div>
    </div>
  )
})

export function SessionListHeader({
  adminSort,
  accountingWindow,
}: {
  adminSort: AdminSort | null
  accountingWindow?: AccountingWindow | null
}) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        'hidden xl:grid h-8 items-center gap-2 border-b border-slate-800 px-3 text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500',
        sessionGridClass(adminSort),
      )}
    >
      <span>Status</span>
      <span>Session</span>
      <span>Project</span>
      <span>Agent</span>
      <span>Model</span>
      <span className="text-right">Tokens in/out</span>
      {adminSort ? (
        <span
          className="text-right"
          title={accountingWindowText(accountingWindow)}
        >
          {ADMIN_HEADER[adminSort]}
        </span>
      ) : null}
      <span className="text-right">Active</span>
      <span className="text-right">Ran</span>
    </div>
  )
}
