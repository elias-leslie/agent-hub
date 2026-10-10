import type { Session } from '@/lib/api/sessions'

export function shortSessionId(id: string): string {
  return id.slice(0, 8)
}

/** True when the harness reported an actual model rather than "unknown". */
export function modelWasObserved(
  session: Pick<Session, 'effective_model' | 'model'>,
): boolean {
  const value = (session.effective_model || session.model || '')
    .trim()
    .toLowerCase()
  return !!value && value !== 'unknown' && !value.endsWith('/unknown')
}

/** Live label without repeating the session status ("completed · completed"). */
export function liveActivityLabel(
  status: string,
  live: { health: string; phase: string } | null | undefined,
): string | null {
  if (!live) return null
  const parts = [...new Set([live.health, live.phase].filter(Boolean))].filter(
    (part) => part !== status,
  )
  return parts.length ? parts.join(' · ') : null
}
