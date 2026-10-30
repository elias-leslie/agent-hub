import type { Session } from '@/lib/api/sessions'

export function hasText(value: string | null | undefined): value is string {
  return Boolean(value?.trim())
}

export function isUsefulLiveSummary(
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

export function formatQuiet(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined) return null
  if (seconds < 60) return `quiet ${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `quiet ${minutes}m`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest > 0 ? `quiet ${hours}h ${rest}m` : `quiet ${hours}h`
}

export function compactState(session: Session) {
  const live = session.live_activity
  const parts = [
    live?.status || session.status,
    live?.phase,
    formatQuiet(live?.quiet_for_seconds),
  ].filter(hasText)
  return parts.join(' · ')
}

export function ScopeLine({
  label,
  paths,
}: {
  label: string
  paths: string[]
}) {
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

// Termination codes the backend writes; anything else is an error message or a status.
const TERMINATION_TEXT: Record<string, string> = {
  session_closed_helper: 'Closed when its work finished',
  turn_interrupted: 'Stopped: the turn was interrupted',
  completion_cached: 'Answered from cache',
  consultation_cancelled: 'Stopped: the consultation was cancelled',
  workflow_completed: 'Closed when its workflow finished',
  workflow_attempt_completed: 'Closed when its workflow step finished',
  session_reaper_completion_timeout: 'Closed after the reply went idle',
  session_reaper_dead_transcript_sync:
    'Closed: its transcript stopped updating',
  session_reaper_global_timeout: 'Closed after going idle',
}

// Ordinary endings: the status already says the session finished, so they are no warning.
const NORMAL_ENDINGS = new Set([
  'session_closed_helper',
  'completion_cached',
  'workflow_completed',
  'workflow_attempt_completed',
])

export function terminationText(reason: string): string {
  const known = TERMINATION_TEXT[reason]
  if (known) return known
  // Snake-case codes (cleanup reasons, joined dead signals) read as words; messages stay as written.
  if (/^[a-z0-9_:+]+$/.test(reason))
    return `Ended: ${reason.replace(/[_+]/g, ' ').replace(/:/g, ', ')}`
  return `Ended: ${reason}`
}

/** Stall, termination, tool-failure and reap notes from the live projection. */
export function liveWarnings(session: Session): string[] {
  const live = session.live_activity
  return [
    live?.stall_reason,
    live?.termination_reason && !NORMAL_ENDINGS.has(live.termination_reason)
      ? terminationText(live.termination_reason)
      : null,
    live?.last_tool_error
      ? `last tool failed${live.last_tool_name ? `: ${live.last_tool_name}` : ''}`
      : null,
    live?.reapable_reason ? `reapable: ${live.reapable_reason}` : null,
  ].filter(hasText)
}

export function primaryScope(session: Session) {
  const writes = session.observed_write_paths ?? []
  const declared = session.declared_scope_paths ?? []
  if (writes.length > 0) return { label: 'Writes', paths: writes }
  if (declared.length > 0) return { label: 'Scope', paths: declared }
  return null
}
