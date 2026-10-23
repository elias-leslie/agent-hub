'use client'

import { ArrowLeft, RefreshCw, Search, X } from 'lucide-react'
import { type ReactNode, useRef, useState } from 'react'
import type { Session, SessionListItem } from '@/lib/api/sessions'
import { cn } from '@/lib/utils'
import { isLiveStatus, useSessionDetail } from '../hooks/useSessionLog'
import { SessionLog } from '../log/SessionLog'
import {
  formatDurationMs,
  formatRelativeTime,
  getExecutionIdentity,
  getSessionLastActive,
  getSessionSourceLabel,
  getSessionTitle,
  getUsageSummary,
} from '../utils'
import { CopyIdButton } from './CopyIdButton'
import { RequestErrorsBadge, requestErrorsText } from './RequestErrorsBadge'
import { hasText, isUsefulLiveSummary, liveWarnings } from './SessionEvidence'
import { StatusCell } from './StatusCell'

function absolute(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function Fact({
  label,
  title,
  children,
}: {
  label: string
  title?: string
  children: ReactNode
}) {
  return (
    <span className="inline-flex min-w-0 items-baseline gap-1" title={title}>
      <span className="text-slate-500">{label}</span>
      <span className="truncate text-slate-200">{children}</span>
    </span>
  )
}

function ToggleButton({
  pressed,
  onClick,
  children,
  title,
}: {
  pressed: boolean
  onClick: () => void
  children: ReactNode
  title: string
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      title={title}
      className={cn(
        'rounded-md border px-2 py-0.5 text-[12px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50',
        pressed
          ? 'border-slate-600 bg-slate-800 text-slate-100'
          : 'border-slate-800 text-slate-300 hover:border-slate-700 hover:bg-slate-900',
      )}
    >
      {children}
    </button>
  )
}

function Facts({
  source,
  onFilterModel,
}: {
  source: Session | SessionListItem
  onFilterModel: (model: string) => void
}) {
  const identity = getExecutionIdentity(source)
  const usage = getUsageSummary({
    usage_known: source.usage_known,
    usage_input_tokens: source.usage_input_tokens,
    usage_output_tokens: source.usage_output_tokens,
    usage_cached_input_tokens: source.usage_cached_input_tokens,
    total_input_tokens: source.total_input_tokens ?? 0,
    total_output_tokens: source.total_output_tokens ?? 0,
  })
  const lastActive = getSessionLastActive(source)
  const duration =
    new Date(lastActive).getTime() - new Date(source.created_at).getTime()
  const filterModel = source.requested_model || source.model
  const children = source.child_session_count ?? 0
  const activeChildren = source.active_child_session_count ?? 0

  return (
    <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[12.5px]">
      <Fact label="project">{source.project_id}</Fact>
      {source.current_branch ? (
        <Fact label="branch">{source.current_branch}</Fact>
      ) : null}
      <Fact label="harness">{getSessionSourceLabel(source)}</Fact>
      <Fact label="model" title={identity.fallbackReason ?? undefined}>
        {identity.showRequested
          ? `${identity.requestedModel} → ${identity.effectiveModel}`
          : identity.effectiveModel}
        {filterModel ? (
          <button
            type="button"
            onClick={() => onFilterModel(filterModel)}
            className="ml-1.5 text-[11px] text-sky-700 dark:text-sky-300 hover:underline"
            title="Show only sessions that requested this model"
          >
            filter
          </button>
        ) : null}
      </Fact>
      <Fact label="started" title={absolute(source.created_at)}>
        {formatRelativeTime(source.created_at)}
      </Fact>
      <Fact label="last active" title={absolute(lastActive)}>
        {formatRelativeTime(lastActive)}
      </Fact>
      <Fact label="ran">{formatDurationMs(duration)}</Fact>
      {source.request_errors ? (
        <Fact
          label="errors"
          title={requestErrorsText(source.request_errors).last}
        >
          <RequestErrorsBadge errors={source.request_errors} />{' '}
          <span className="text-slate-400">
            {requestErrorsText(source.request_errors).last}
          </span>
        </Fact>
      ) : null}
      <Fact label="tokens" title={usage.title}>
        {usage.known ? (
          `in ${usage.input.toLocaleString()} · out ${usage.output.toLocaleString()}${usage.cached ? ` · cached ${usage.cached.toLocaleString()}` : ''}`
        ) : (
          <span className="italic text-slate-500">usage not captured</span>
        )}
      </Fact>
      {source.message_count !== undefined && source.message_count !== null ? (
        <Fact label="messages">{source.message_count.toLocaleString()}</Fact>
      ) : null}
      {children > 0 ? (
        <Fact label="sub-agents">
          {children.toLocaleString()}
          {activeChildren ? ` (${activeChildren} running)` : ''}
        </Fact>
      ) : null}
      {source.external_id ? (
        <Fact label="task" title={source.external_id}>
          <span className="font-mono text-[12px]">{source.external_id}</span>
        </Fact>
      ) : null}
    </div>
  )
}

function LiveLine({ session }: { session: Session }) {
  const live = session.live_activity
  const summary = isUsefulLiveSummary(live?.summary) ? live?.summary : null
  const writes = session.observed_write_paths ?? []
  const warnings = liveWarnings(session)
  const isLive = isLiveStatus(session.status)
  if (!isLive && warnings.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
      {isLive && live?.current_tool_name ? (
        <span className="font-mono text-sky-700 dark:text-sky-300">
          now: {live.current_tool_name}
        </span>
      ) : null}
      {isLive && hasText(summary) ? (
        <span className="text-slate-300">{summary}</span>
      ) : null}
      {writes.length > 0 ? (
        <span className="text-slate-400" title={writes.join('\n')}>
          files written {writes.length}
        </span>
      ) : null}
      {warnings.map((note) => (
        <span
          key={note}
          className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 font-mono text-[11px] text-amber-800 dark:text-amber-200/90"
        >
          {note}
        </span>
      ))}
    </div>
  )
}

/**
 * The selected session, expanded in place under its row: a compact facts
 * strip and the session's log. On phones it fills the screen with Back.
 */
export function SessionInline({
  sessionId,
  listRow,
  onClose,
  onSelect,
  onFilterModel,
}: {
  sessionId: string
  /** The list row, or null when the session is outside the loaded list. */
  listRow: SessionListItem | null
  onClose: () => void
  onSelect: (id: string) => void
  onFilterModel: (model: string) => void
}) {
  const live = isLiveStatus(listRow?.status)
  const detail = useSessionDetail(sessionId, live)
  const session = detail.data ?? null
  const source = session ?? listRow
  const [details, setDetails] = useState(false)
  const [raw, setRaw] = useState(false)
  const [search, setSearch] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const title = source
    ? getSessionTitle(source)
    : `session ${sessionId.slice(0, 8)}`
  const status = source?.status ?? ''

  return (
    <section
      aria-label={`Session ${title}`}
      data-testid="session-inline"
      className="fixed inset-0 z-40 flex flex-col bg-slate-950 md:static md:z-auto md:max-h-[72vh] md:border-y md:border-l-2 md:border-y-slate-700/70 md:border-l-amber-400/70 md:bg-slate-900/40"
    >
      <div className="flex flex-col gap-1.5 border-b border-slate-800 px-3 py-2 md:px-4">
        <div className="flex min-w-0 items-center gap-2">
          <button
            type="button"
            onClick={onClose}
            aria-label="Back to sessions"
            className="-ml-1 rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50 md:hidden"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          {source ? (
            <span className="shrink-0">
              <StatusCell
                status={status}
                liveActivity={source.live_activity}
                showLabel
              />
            </span>
          ) : null}
          <h2
            className="min-w-0 truncate text-[13px] font-semibold text-slate-100"
            title={title}
          >
            {title}
          </h2>
          <span className="hidden shrink-0 font-mono text-[11px] text-slate-500 sm:inline">
            {sessionId.slice(0, 8)}
          </span>
          <CopyIdButton
            id={sessionId}
            className="hidden shrink-0 text-slate-400 sm:block"
          />
          {session?.parent_session_id ? (
            <button
              type="button"
              onClick={() => onSelect(session.parent_session_id as string)}
              className="hidden shrink-0 text-[12px] text-sky-700 dark:text-sky-300 hover:underline sm:inline"
            >
              parent ↗
            </button>
          ) : null}
          <span className="flex-1" />
          <label className="relative hidden items-center sm:flex">
            <Search className="pointer-events-none absolute left-2 h-3 w-3 text-slate-500" />
            <span className="sr-only">Search this session</span>
            <input
              data-session-search
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search this session"
              className="w-36 rounded-md border lg:w-48 border-slate-800 bg-slate-950 py-0.5 pl-6 pr-2 text-[12px] text-slate-200 placeholder:text-slate-500 focus:border-slate-600 focus:outline-none"
            />
          </label>
          <ToggleButton
            pressed={details}
            onClick={() => setDetails((value) => !value)}
            title="Show thinking, usage and memory events"
          >
            Details
          </ToggleButton>
          <ToggleButton
            pressed={raw}
            onClick={() => setRaw((value) => !value)}
            title="Unfolded rows show the recorded JSON"
          >
            Raw
          </ToggleButton>
          <button
            type="button"
            onClick={onClose}
            aria-label="Collapse session"
            title="Collapse (Esc)"
            className="hidden rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50 md:block"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <label className="relative flex items-center sm:hidden">
          <Search className="pointer-events-none absolute left-2 h-3 w-3 text-slate-500" />
          <span className="sr-only">Search this session</span>
          <input
            data-session-search
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search this session"
            className="w-full rounded-md border border-slate-800 bg-slate-950 py-1 pl-6 pr-2 text-[13px] text-slate-200 placeholder:text-slate-500 focus:border-slate-600 focus:outline-none"
          />
        </label>
        {source ? (
          <Facts source={source} onFilterModel={onFilterModel} />
        ) : null}
        {!listRow && session ? (
          <div className="text-[12px] text-slate-500">
            Not among the rows loaded below; it may be filtered out or further
            down
            {session.parent_session_id
              ? ' (sub-agents are listed only with Include sub-agents on)'
              : ''}
            .
          </div>
        ) : null}
        {session ? <LiveLine session={session} /> : null}
        {detail.error && !session ? (
          <div className="flex items-center gap-2 text-[12px] text-rose-700 dark:text-rose-200">
            <span>Session details failed to load.</span>
            <button
              type="button"
              onClick={() => void detail.refetch()}
              className="inline-flex items-center gap-1 rounded border border-rose-400/30 px-2 py-0.5 hover:bg-rose-500/10"
            >
              <RefreshCw className="h-3 w-3" />
              Retry
            </button>
          </div>
        ) : null}
        {!source && detail.isLoading ? (
          <div className="text-[12px] text-slate-500">Loading session…</div>
        ) : null}
      </div>
      <div
        ref={scrollRef}
        className="min-h-0 flex-1 overflow-y-auto px-1.5 md:px-2.5"
      >
        <SessionLog
          sessionId={sessionId}
          childCount={source?.child_session_count ?? 0}
          activeChildren={source?.active_child_session_count ?? 0}
          live={isLiveStatus(status)}
          details={details}
          raw={raw}
          search={search}
          scrollRef={scrollRef}
          onSelect={onSelect}
        />
      </div>
    </section>
  )
}
