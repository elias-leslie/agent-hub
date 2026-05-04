import { Maximize2, RefreshCw } from 'lucide-react'

import { EventTimeline } from '@/components/timeline'
import type { Session, SessionEventsResponse, SessionListItem } from '@/lib/api'
import { formatDuration } from '../utils'
import { CopyIdButton } from './CopyIdButton'

function hasText(value: string | null | undefined): value is string {
  return Boolean(value?.trim())
}

function isUsefulLiveSummary(
  summary: string | null | undefined,
): summary is string {
  const value = summary?.trim()
  if (!value) return false
  const normalized = value.toLowerCase()
  return (
    normalized !== 'execution completed' &&
    normalized !== 'execution complete' &&
    !normalized.startsWith('transcript sync heartbeat')
  )
}

function formatQuiet(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined) return null
  if (seconds < 60) return `quiet ${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `quiet ${minutes}m`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest > 0 ? `quiet ${hours}h ${rest}m` : `quiet ${hours}h`
}

function compactState(session: Session) {
  const live = session.live_activity
  const parts = [
    live?.status || session.status,
    live?.phase,
    formatQuiet(live?.quiet_for_seconds),
  ].filter(hasText)
  return parts.join(' · ')
}

function ScopeLine({ label, paths }: { label: string; paths: string[] }) {
  if (paths.length === 0) return null
  const visiblePaths = paths.slice(0, 5)
  const remaining = paths.length - visiblePaths.length

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
      <span className="font-medium uppercase tracking-[0.16em]">{label}</span>
      {visiblePaths.map((path) => (
        <span
          key={`${label}-${path}`}
          className="max-w-[28rem] truncate border border-slate-800/80 bg-slate-900/45 px-2 py-1 font-mono text-slate-400"
          title={path}
        >
          {path}
        </span>
      ))}
      {remaining > 0 ? (
        <span className="border border-slate-800/80 bg-slate-900/45 px-2 py-1 font-mono text-slate-500">
          +{remaining}
        </span>
      ) : null}
    </div>
  )
}

export function ExpandedRowContent({
  session,
  expandedData,
  eventsData,
  isLoading,
}: {
  session: SessionListItem
  expandedData: Session | null
  eventsData: SessionEventsResponse | null
  isLoading: boolean
}) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-slate-500">
        <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
        Loading session evidence…
      </div>
    )
  }

  if (!expandedData || !eventsData) {
    return (
      <div className="px-4 py-6 text-sm text-slate-500">
        Session evidence unavailable.
      </div>
    )
  }

  const live = expandedData.live_activity
  const eventCount = expandedData.event_count ?? eventsData.total
  const messageCount = expandedData.message_count ?? session.message_count
  const usefulLiveSummary = isUsefulLiveSummary(live?.summary)
    ? live.summary
    : null
  const summary = expandedData.summary_oneliner?.trim() || usefulLiveSummary
  const duration = formatDuration(
    expandedData.created_at,
    expandedData.updated_at,
  )
  const writes = expandedData.observed_write_paths ?? []
  const declared = expandedData.declared_scope_paths ?? []
  const reads = expandedData.observed_read_paths ?? []
  const primaryScope =
    writes.length > 0
      ? { label: 'Writes', paths: writes }
      : declared.length > 0
        ? { label: 'Scope', paths: declared }
        : null
  const liveWarnings = [
    live?.stall_reason,
    live?.termination_reason ? `terminated: ${live.termination_reason}` : null,
    live?.last_tool_error
      ? `last tool failed${live.last_tool_name ? `: ${live.last_tool_name}` : ''}`
      : null,
    live?.reapable_reason ? `reapable: ${live.reapable_reason}` : null,
  ].filter(hasText)

  return (
    <div className="border-t border-slate-800/70 bg-slate-950/92">
      <div className="flex flex-wrap items-start gap-3 px-4 py-2.5">
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
            <span className="font-mono text-slate-200">
              {compactState(expandedData)}
            </span>
            {hasText(summary) ? (
              <span
                className="max-w-[42rem] truncate text-slate-300"
                title={summary}
              >
                {summary}
              </span>
            ) : null}
            {live?.current_tool_name ? (
              <span className="text-sky-300">
                tool {live.current_tool_name}
              </span>
            ) : null}
            <span className="text-slate-500">
              {messageCount ?? 0} messages · {eventCount} events · {duration}
            </span>
            {reads.length > 0 ? (
              <span className="text-slate-600">reads {reads.length}</span>
            ) : null}
          </div>

          {primaryScope ? (
            <ScopeLine label={primaryScope.label} paths={primaryScope.paths} />
          ) : (
            <div className="text-[11px] text-slate-600">No writes recorded</div>
          )}

          {liveWarnings.length > 0 ? (
            <div className="flex flex-wrap gap-1.5 font-mono text-[11px] text-amber-200/90">
              {liveWarnings.map((note) => (
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

        <div className="flex shrink-0 items-center gap-1">
          <a
            href={`/sessions/${session.id}`}
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-medium text-slate-300 transition-colors hover:bg-slate-800 hover:text-slate-100"
          >
            <Maximize2 className="h-3 w-3" />
            Full view
          </a>
          <CopyIdButton id={session.id} />
        </div>
      </div>

      <div className="h-[72vh] min-h-[520px] max-h-[760px] border-t border-slate-800/70">
        <EventTimeline events={eventsData.events} density="compact" />
      </div>
    </div>
  )
}
