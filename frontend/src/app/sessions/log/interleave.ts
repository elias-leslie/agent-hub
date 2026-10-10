import type { SessionListItem } from '@/lib/api/sessions'
import type { LogEntry } from './entries'

export type LogItem =
  | { type: 'turn'; key: string; turn: number; at: string }
  | { type: 'entry'; key: string; entry: LogEntry }
  | { type: 'children'; key: string; children: SessionListItem[] }

function time(value: string): number {
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? 0 : parsed
}

/**
 * Places sub-agents in the log at their start time and adds turn separators.
 * Children started before the first loaded entry are held back while older
 * log windows remain (`hasEarlier`), so they appear once that history loads.
 * Children with no log entries between them form one batch.
 */
export function interleave(
  entries: readonly LogEntry[],
  children: readonly SessionListItem[],
  hasEarlier: boolean,
): { items: LogItem[]; heldBack: number } {
  const items: LogItem[] = []
  const firstAt = entries.length
    ? time(entries[0].at)
    : Number.POSITIVE_INFINITY
  const pending = [...children].sort(
    (a, b) => time(a.created_at) - time(b.created_at),
  )
  let heldBack = 0
  let next = 0
  if (hasEarlier) {
    while (next < pending.length && time(pending[next].created_at) < firstAt) {
      next += 1
      heldBack += 1
    }
  }

  const flushUntil = (limit: number) => {
    const batch: SessionListItem[] = []
    while (next < pending.length && time(pending[next].created_at) <= limit) {
      batch.push(pending[next])
      next += 1
    }
    if (batch.length)
      items.push({
        type: 'children',
        key: `children:${batch[0].id}`,
        children: batch,
      })
  }

  let lastTurn: number | null = null
  for (const entry of entries) {
    flushUntil(time(entry.at) - 1)
    if (entry.turn !== lastTurn) {
      items.push({
        type: 'turn',
        key: `turn:${entry.id}`,
        turn: entry.turn,
        at: entry.at,
      })
      lastTurn = entry.turn
    }
    items.push({ type: 'entry', key: entry.id, entry })
  }
  flushUntil(Number.POSITIVE_INFINITY)
  return { items, heldBack }
}
