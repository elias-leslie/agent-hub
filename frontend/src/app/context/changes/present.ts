import type {
  ChangeKind,
  LaterWrite,
  QueueRow,
  Reach,
  TargetKind,
  Writer,
} from '@/lib/api/context-changes'
import { ago, harnessLabel, signedTok, tok } from '../format'

export const KIND_LABEL: Record<TargetKind, string> = {
  memory: 'Memory',
  prompt: 'Prompt',
  placement: 'Placement',
}

export const CHANGE_LABEL: Record<ChangeKind, string> = {
  create: 'New',
  update: 'Edited',
  delete: 'Deleted',
  archive: 'Archived',
  scope: 'Re-scoped',
  placement: 'Rules changed',
}

/** Short form of a session id: aico-widget-a36fa317 -> a36fa317, delivery:ab12… stays marked as a delivery. */
export function sessionShort(session: string): string {
  const delivery = session.startsWith('delivery:')
  const raw = delivery ? session.slice('delivery:'.length) : session
  const tail = raw.split(/[-:]/).pop() ?? raw
  const short = (tail.length >= 6 ? tail : raw).slice(0, 8)
  return delivery ? `delivery ${short}` : short
}

const WRITER_KIND: Record<string, string> = {
  agent: 'agent',
  client: 'client app',
  owner: 'you',
  system: 'system',
}

/** `a36fa317 · Claude Code · implementation`; parts that were not recorded show as an em dash. */
export function writerLabel(w: Writer): string {
  const who = w.session
    ? sessionShort(w.session)
    : w.delivery
      ? `delivery ${w.delivery.slice(0, 8)}`
      : (WRITER_KIND[w.kind ?? ''] ?? 'unknown writer')
  const harness = w.harness ? harnessLabel(w.harness) : '—'
  const role = w.work_role ?? (w.coordinator ? 'coordinator' : '—')
  return `${who} · ${harness} · ${role}`
}

export function writersLabel(row: Pick<QueueRow, 'writers'>): string {
  if (row.writers.length === 0) return 'writer unknown'
  const labels = row.writers.map(writerLabel)
  return labels.length > 2
    ? `${labels.slice(0, 2).join(' + ')} + ${labels.length - 2} more`
    : labels.join(' + ')
}

/** The session a row belongs to for grouping, or null when no writer session is known. */
export function groupSession(row: Pick<QueueRow, 'sessions'>): string | null {
  return row.sessions[0] ?? null
}

export function perStart(row: Pick<QueueRow, 'delta_tokens'>): string {
  return row.delta_tokens == null
    ? '—'
    : `${signedTok(row.delta_tokens)} tok/start`
}

export function perDay(row: Pick<QueueRow, 'tokens_per_day'>): string {
  return row.tokens_per_day == null
    ? '—'
    : `${signedTok(row.tokens_per_day)} tok/day`
}

/** Who receives it. Unknown reach (no recorded delivery yet) says so; it is never 0. */
export function reachLabel(
  row: Pick<QueueRow, 'reach' | 'first_at' | 'change'>,
): {
  short: string
  detail: string
} {
  const reach: Reach | null = row.reach
  if (!reach) {
    return {
      short: 'reach unknown',
      detail:
        'No start has been recorded since this change yet, so how many sessions get it is not known.',
    }
  }
  const before =
    new Date(reach.until).getTime() <= new Date(row.first_at).getTime() + 1000
  const days = reach.days >= 1 ? Math.round(reach.days) : 1
  const window = before
    ? `Counted over the ${days} days before the change`
    : `Counted since the change (${days}d)`
  const who = reach.receivers
    .slice(0, 4)
    .map((r) => `${harnessLabel(r.harness)} ${r.role ?? '—'} ${r.starts}`)
    .join(', ')
  const subs = reach.subagent_starts
    ? `, plus ${reach.subagent_starts} sub-agent starts`
    : ''
  return {
    short: `~${tok(Math.round(reach.starts_per_day))} starts/day`,
    detail: `${window}: ${reach.starts} starts${subs}. ${who || 'No receivers listed'}.`,
  }
}

export function receiversShort(row: Pick<QueueRow, 'reach'>): string {
  const receivers = row.reach?.receivers ?? []
  if (receivers.length === 0) return ''
  const harnesses = [...new Set(receivers.map((r) => harnessLabel(r.harness)))]
  const roles = [...new Set(receivers.map((r) => r.role ?? '—'))]
  return `${harnesses.join(', ')} · ${roles.length > 3 ? `${roles.length} roles` : roles.join(', ')}`
}

export function laterWriteText(w: LaterWrite): string {
  const who =
    w.writer_kind === 'system'
      ? 'system'
      : w.writer_kind === 'owner'
        ? 'your'
        : (w.writer_kind ?? 'other')
  return `${who} ${w.action} ${ago(w.at)}`
}

export function alsoUndoesText(list: LaterWrite[]): string {
  const owner = list.filter((w) => w.writer_kind === 'owner').length
  const other = list.length - owner
  const parts: string[] = []
  if (owner) parts.push(`${owner} later edit${owner > 1 ? 's' : ''} of yours`)
  if (other)
    parts.push(`${other} later system or other write${other > 1 ? 's' : ''}`)
  return parts.join(' and ')
}

/** First word of the resulting scope, for the scope filter: global, project, role... */
export function scopeWord(
  row: Pick<QueueRow, 'scope_after' | 'scope_before' | 'target_kind'>,
): string {
  if (row.target_kind === 'placement') return 'placement'
  const word = row.scope_after.split(' ')[0]
  return ['deleted', 'archived', 'disabled'].includes(word)
    ? (row.scope_before ?? word).split(' ')[0]
    : word
}

export function preview(text: string, max = 160): string {
  const flat = text.replace(/\s+/g, ' ').trim()
  return flat.length > max ? `${flat.slice(0, max)}…` : flat
}

export interface Group {
  id: string
  session: string | null
  rows: QueueRow[]
}

/** Rows of one session together (newest first). One-row sessions and rows with no known session stay singles. */
export function groupRows(rows: QueueRow[]): {
  groups: Group[]
  singles: QueueRow[]
} {
  const bySession = new Map<string, QueueRow[]>()
  for (const row of rows) {
    const s = groupSession(row)
    if (s) bySession.set(s, [...(bySession.get(s) ?? []), row])
  }
  const groups: Group[] = []
  const singles: QueueRow[] = []
  const seen = new Set<string>()
  for (const row of rows) {
    const s = groupSession(row)
    const members = s ? bySession.get(s) : undefined
    if (s && members && members.length > 1) {
      if (!seen.has(s)) {
        seen.add(s)
        groups.push({ id: `group:${s}`, session: s, rows: members })
      }
    } else singles.push(row)
  }
  return { groups, singles }
}
