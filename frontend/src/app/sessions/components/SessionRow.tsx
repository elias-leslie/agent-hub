import { memo } from 'react'
import { durationPercent, durationSeconds } from '@/lib/api/duration-split'
import type { SessionListItem } from '@/lib/api/sessions'
import { cn } from '@/lib/utils'
import {
  formatDurationMs,
  formatRelativeTime,
  getExecutionIdentity,
  getSessionLastActive,
  getSessionSourceLabel,
  getSessionTitle,
  getUsageSummary,
} from '../utils'
import { StatusCell } from './StatusCell'

/** Column template shared by the header and rows so they always line up. */
export function sessionGridClass() {
  // Title is the only flexible column; branch appears only on wide screens.
  return 'xl:grid xl:grid-cols-[84px_minmax(8rem,1fr)_100px_90px_110px_36px_112px_150px_60px_60px] 2xl:grid-cols-[84px_minmax(10rem,1fr)_100px_90px_110px_100px_36px_112px_150px_60px_60px]'
}

function absolute(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

export const SessionRow = memo(function SessionRow({
  session,
  isCursor,
  isSelected,
  onClick,
}: {
  session: SessionListItem
  /** Keyboard cursor; carries the roving tabindex. */
  isCursor: boolean
  /** Row whose session is expanded beneath it. */
  isSelected: boolean
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
  const accounting = session.activity_accounting
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
        'cursor-pointer gap-2 border-b border-slate-800/50 px-3 py-2 text-[13px] outline-none transition-colors xl:min-h-12 xl:items-center',
        sessionGridClass(),
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
        <div className="order-2 shrink-0 xl:order-none">
          <StatusCell
            status={session.status}
            liveActivity={session.live_activity}
            showLabel
          />
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
        </div>
      </div>

      {/* Phone: line 2 is project · kind · last active · tokens */}
      <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 text-[12px] text-slate-400 xl:contents">
        <span className="truncate md:text-[13px] md:text-slate-300">
          {session.project_id}
        </span>
        <span className="truncate">{source}</span>
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
          className="hidden truncate font-mono text-[12px] text-slate-500 2xl:block"
          title={session.current_branch ?? undefined}
        >
          {session.current_branch || '—'}
        </span>
        <span
          className={cn(
            'font-mono text-[12px] tabular-nums md:text-right',
            children > 0 ? 'text-slate-300' : 'hidden text-slate-600 md:inline',
          )}
          title={
            children > 0
              ? `${children} sub-agent${children === 1 ? '' : 's'}${activeChildren ? `, ${activeChildren} active` : ''}`
              : 'No sub-agents'
          }
        >
          {children > 0 ? (
            <>
              <span className="md:hidden">sub-agents </span>
              {children}
            </>
          ) : (
            '—'
          )}
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
        <span
          className="text-[11px] text-slate-300 xl:text-right"
          title={
            accounting
              ? `${durationSeconds(accounting.admin_seconds)} admin / ${durationSeconds(accounting.denominator_seconds)} recorded non-wait tool time; unknown ${durationPercent(accounting.unknown_share)}; duration on ${accounting.tools_sampled - accounting.tools_missing_duration}/${accounting.tools_sampled} calls${accounting.events_truncated ? '; sample capped' : ''}.`
              : 'Tool-time accounting unavailable from this server.'
          }
        >
          <span className="block tabular-nums">
            Admin {durationPercent(accounting?.admin_share)} · Other{' '}
            {durationPercent(accounting?.other_share)}
          </span>
          <span className="block text-slate-400">
            {session.work_role?.label ?? 'Unknown'}
            {accounting &&
            (accounting.tools_missing_duration > 0 ||
              accounting.events_truncated)
              ? ' · partial'
              : ''}
          </span>
        </span>
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

export function SessionListHeader() {
  return (
    <div
      aria-hidden="true"
      className={cn(
        'hidden xl:grid h-8 items-center gap-2 border-b border-slate-800 px-3 text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500',
        sessionGridClass(),
      )}
    >
      <span>Status</span>
      <span>Session</span>
      <span>Project</span>
      <span>Source</span>
      <span className="hidden lg:block">Model</span>
      <span className="hidden 2xl:block">Branch</span>
      <span className="text-right" title="Sub-agents">
        Sub
      </span>
      <span className="text-right">Tokens</span>
      <span className="text-right">Tool time · role</span>
      <span className="text-right">Active</span>
      <span className="hidden text-right lg:block">Duration</span>
    </div>
  )
}
