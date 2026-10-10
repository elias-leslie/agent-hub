import { ArrowLeft, Maximize2, RefreshCw, X } from 'lucide-react'
import Link from 'next/link'
import type { ReactNode } from 'react'
import { EventTimeline } from '@/components/timeline'
import type { Session, SessionListItem } from '@/lib/api/sessions'
import { useSessionPreview } from '../hooks/useSessionPreview'
import {
  formatDurationMs,
  formatRelativeTime,
  getExecutionIdentity,
  getSessionKindLabel,
  getSessionLastActive,
  getSessionTitle,
  getUsageSummary,
} from '../utils'
import { CopyIdButton } from './CopyIdButton'
import {
  compactState,
  hasText,
  isUsefulLiveSummary,
  liveWarnings,
  primaryScope,
  ScopeLine,
} from './SessionEvidence'
import { StatusCell } from './StatusCell'

function absolute(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-[0.12em] text-slate-500">
        {label}
      </dt>
      <dd className="truncate text-[13px] text-slate-200">{children}</dd>
    </div>
  )
}

function Section({
  title,
  aside,
  children,
}: {
  title: string
  aside?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="border-t border-slate-800/70 px-4 py-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-[11px] font-medium uppercase tracking-[0.14em] text-slate-400">
          {title}
        </h3>
        {aside}
      </div>
      {children}
    </section>
  )
}

function Muted({ children }: { children: ReactNode }) {
  return <p className="text-[12px] text-slate-500">{children}</p>
}

export function SessionPreview({
  sessionId,
  listRow,
  onClose,
  onFilterModel,
}: {
  sessionId: string
  /** The list row when loaded, so the header renders before the detail fetch. */
  listRow: SessionListItem | null
  onClose: () => void
  onFilterModel: (model: string) => void
}) {
  const preview = useSessionPreview(sessionId)
  const session = preview.session
  const base = session ?? listRow
  const title = base
    ? getSessionTitle(base)
    : `session ${sessionId.slice(0, 8)}`

  return (
    <aside
      aria-label="Session preview"
      data-testid="session-preview"
      className="fixed inset-0 z-40 flex flex-col overflow-hidden bg-slate-950 md:inset-y-0 md:left-auto md:right-0 md:w-[min(600px,92vw)] md:border-l md:border-slate-800 md:shadow-2xl xl:sticky xl:top-[var(--sessions-top,0px)] xl:z-auto xl:h-[calc(100dvh-var(--sessions-top,0px))] xl:w-auto xl:shadow-none"
    >
      <header className="flex items-start gap-2 border-b border-slate-800 px-4 py-3">
        <button
          type="button"
          onClick={onClose}
          aria-label="Back to sessions"
          className="-ml-1 rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50 md:hidden"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>
        <div className="min-w-0 flex-1 space-y-1">
          <h2
            className="line-clamp-2 text-sm font-semibold text-slate-100"
            title={title}
          >
            {title}
          </h2>
          <div className="flex flex-wrap items-center gap-2 text-[12px] text-slate-400">
            {base ? (
              <StatusCell
                status={base.status}
                liveActivity={base.live_activity}
                showLabel
              />
            ) : null}
            <span className="truncate font-mono text-[11px] text-slate-500">
              {sessionId}
            </span>
            <CopyIdButton id={sessionId} />
          </div>
        </div>
        <Link
          href={`/sessions/${sessionId}`}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-slate-800 px-2 py-1 text-[12px] text-slate-200 hover:border-slate-700 hover:bg-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
        >
          <Maximize2 className="h-3 w-3" />
          Open
        </Link>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close preview"
          title="Close (Esc)"
          className="hidden rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50 md:block"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {preview.sessionError && !session ? (
          <div className="flex items-center justify-between gap-3 px-4 py-4 text-[13px] text-rose-200">
            <span>Session details failed to load.</span>
            <button
              type="button"
              onClick={() => void preview.refetchSession()}
              className="inline-flex items-center gap-1.5 rounded-md border border-rose-400/30 px-2 py-1 text-[12px] hover:bg-rose-500/10"
            >
              <RefreshCw className="h-3 w-3" />
              Retry
            </button>
          </div>
        ) : null}

        {base ? (
          <Facts session={session} row={base} onFilterModel={onFilterModel} />
        ) : null}
        {!base && preview.isLoadingSession ? (
          <div className="px-4 py-6 text-[13px] text-slate-500">
            Loading session…
          </div>
        ) : null}

        {session?.parent_session_id ? (
          <Section title="Parent">
            <Link
              href={`/sessions/${session.parent_session_id}`}
              className="font-mono text-[12px] text-sky-300 hover:underline"
            >
              {session.parent_session_id}
            </Link>
          </Section>
        ) : null}

        {(session?.child_session_count ?? 0) > 0 ? (
          <Section
            title="Sub-agents"
            aside={
              <span className="font-mono text-[11px] text-slate-500">
                {preview.subagents.length < preview.subagentsTotal
                  ? `showing ${preview.subagents.length} of ${preview.subagentsTotal}`
                  : preview.subagentsTotal}
              </span>
            }
          >
            {preview.isLoadingSubagents ? (
              <Muted>Loading sub-agents…</Muted>
            ) : null}
            {preview.subagentsError ? (
              <Muted>Sub-agents failed to load.</Muted>
            ) : null}
            <ul className="divide-y divide-slate-800/60">
              {preview.subagents.map((child) => {
                const usage = getUsageSummary(child)
                return (
                  <li key={child.id}>
                    <Link
                      href={`/sessions/${child.id}`}
                      className="grid grid-cols-[84px_minmax(0,1fr)_auto] items-center gap-2 py-1.5 text-[12px] hover:bg-slate-900/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber-400/50"
                    >
                      <StatusCell
                        status={child.status}
                        liveActivity={child.live_activity}
                        showLabel
                      />
                      <span className="truncate text-slate-200">
                        {getSessionTitle(child)}
                      </span>
                      <span
                        className="font-mono tabular-nums text-slate-500"
                        title={usage.title}
                      >
                        {usage.label}
                      </span>
                    </Link>
                  </li>
                )
              })}
            </ul>
          </Section>
        ) : null}

        {session ? <LiveEvidence session={session} /> : null}

        <Section
          title="Latest activity"
          aside={
            preview.eventsTotal !== null ? (
              <span className="font-mono text-[11px] text-slate-500">
                last {preview.latestEvents.length} of {preview.eventsTotal}
              </span>
            ) : null
          }
        >
          {preview.isLoadingEvents ? <Muted>Loading events…</Muted> : null}
          {preview.eventsError ? <Muted>Events failed to load.</Muted> : null}
          {!preview.isLoadingEvents &&
          !preview.eventsError &&
          preview.latestEvents.length === 0 ? (
            <Muted>No messages or tool calls recorded.</Muted>
          ) : null}
          {preview.latestEvents.length > 0 ? (
            <div className="h-[420px] overflow-hidden rounded border border-slate-800/70">
              <EventTimeline events={preview.latestEvents} density="compact" />
            </div>
          ) : null}
        </Section>
      </div>
    </aside>
  )
}

function Facts({
  session,
  row,
  onFilterModel,
}: {
  session: Session | null
  row: SessionListItem | Session
  onFilterModel: (model: string) => void
}) {
  const source = session ?? row
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
  const filterModel = source.requested_model || source.model

  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 px-4 py-3 sm:grid-cols-3">
      <Fact label="Project">{source.project_id}</Fact>
      <Fact label="Branch">{source.current_branch || '—'}</Fact>
      <Fact label="Kind">
        {getSessionKindLabel(source.session_type)} · {source.provider}
      </Fact>
      <Fact label="Agent">{source.agent_slug || '—'}</Fact>
      <Fact label="Model">
        <span title={identity.fallbackReason ?? undefined}>
          {identity.showRequested
            ? `${identity.requestedModel} → ${identity.effectiveModel}`
            : identity.effectiveModel}
        </span>
        {filterModel ? (
          <button
            type="button"
            onClick={() => onFilterModel(filterModel)}
            className="ml-2 text-[11px] text-sky-300 hover:underline"
          >
            filter
          </button>
        ) : null}
      </Fact>
      <Fact label="Tokens">
        <span
          title={usage.title}
          className={usage.known ? '' : 'text-slate-500'}
        >
          {usage.known
            ? `in ${usage.input.toLocaleString()} · out ${usage.output.toLocaleString()}${usage.cached ? ` · cached ${usage.cached.toLocaleString()}` : ''}`
            : 'usage not captured'}
        </span>
      </Fact>
      <Fact label="Started">
        <span title={absolute(source.created_at)}>
          {formatRelativeTime(source.created_at)}
        </span>
      </Fact>
      <Fact label="Last active">
        <span title={absolute(lastActive)}>
          {formatRelativeTime(lastActive)}
        </span>
      </Fact>
      <Fact label="Duration">
        {formatDurationMs(
          new Date(lastActive).getTime() -
            new Date(source.created_at).getTime(),
        )}
      </Fact>
      {source.external_id ? (
        <Fact label="Task / external id">
          <span className="font-mono text-[12px]" title={source.external_id}>
            {source.external_id}
          </span>
        </Fact>
      ) : null}
      {session?.message_count !== undefined &&
      session?.message_count !== null ? (
        <Fact label="Messages · events">
          {session.message_count.toLocaleString()} ·{' '}
          {(session.event_count ?? 0).toLocaleString()}
        </Fact>
      ) : null}
    </dl>
  )
}

function LiveEvidence({ session }: { session: Session }) {
  const live = session.live_activity
  const summary = isUsefulLiveSummary(live?.summary) ? live?.summary : null
  const scope = primaryScope(session)
  const warnings = liveWarnings(session)
  const reads = session.observed_read_paths ?? []

  return (
    <Section title="State">
      <div className="space-y-1.5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
          <span className="font-mono text-slate-200">
            {compactState(session)}
          </span>
          {live?.current_tool_name ? (
            <span className="text-sky-300">tool {live.current_tool_name}</span>
          ) : null}
          {reads.length > 0 ? (
            <span className="text-slate-500">reads {reads.length}</span>
          ) : null}
        </div>
        {hasText(summary) ? (
          <p className="text-[12px] text-slate-300">{summary}</p>
        ) : null}
        {scope ? (
          <ScopeLine label={scope.label} paths={scope.paths} />
        ) : (
          <div className="text-[11px] text-slate-600">No writes recorded</div>
        )}
        {warnings.length > 0 ? (
          <div className="flex flex-wrap gap-1.5 font-mono text-[11px] text-amber-200/90">
            {warnings.map((note) => (
              <span
                key={note}
                className="border border-amber-900/40 bg-amber-950/15 px-2 py-1"
              >
                {note}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </Section>
  )
}
