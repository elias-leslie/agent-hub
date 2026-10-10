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

/** Stall, termination, tool-failure and reap notes from the live projection. */
export function liveWarnings(session: Session): string[] {
  const live = session.live_activity
  return [
    live?.stall_reason,
    live?.termination_reason ? `terminated: ${live.termination_reason}` : null,
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
