export { formatTokens } from '@/lib/formatters'

export function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  if (ms < 3600000)
    return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
  return `${Math.floor(ms / 3600000)}h ${Math.floor((ms % 3600000) / 60000)}m`
}

const CHILD_ID_IN_CONTENT = /Child session ([0-9a-f]{8}-[0-9a-f-]{27,})/i

/** Child session id carried by a child_session_* event, if any. */
export function childSessionIdOf(event: {
  event_type: string
  tool_output: Record<string, unknown> | null
  content: string | null
}): string | null {
  if (!event.event_type.startsWith('child_session_')) return null
  const fromPayload = event.tool_output?.child_session_id
  if (typeof fromPayload === 'string' && fromPayload) return fromPayload
  return event.content?.match(CHILD_ID_IN_CONTENT)?.[1] ?? null
}
