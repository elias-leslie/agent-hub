import type { ContextDays, MatrixCell } from '@/lib/api/context-observability'

/** A cell with no start for this long is shown as stale even though it is inside the window. */
export const STALE_AFTER_DAYS = 3
/** Fewer starts than this and the median is shown with its n, not as a settled number. */
export const FEW_STARTS = 3

export const HARNESS_LABEL: Record<string, string> = {
  claude: 'Claude Code',
  codex: 'Codex',
  pi: 'Pi',
  agent_hub: 'Agent Hub',
}

export function harnessLabel(harness: string): string {
  return HARNESS_LABEL[harness] ?? harness
}

/** Tokens as 47.9K; unknown is an em dash, never 0. */
export function tok(value: number | null | undefined): string {
  if (value == null) return '—'
  if (value >= 100_000) return `${Math.round(value / 1000)}K`
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`
  return String(value)
}

export function signedTok(value: number | null | undefined): string {
  if (value == null) return '—'
  if (value === 0) return '0'
  return `${value > 0 ? '+' : '−'}${tok(Math.abs(value))}`
}

export function signedPct(value: number | null | undefined): string {
  if (value == null) return '—'
  const rounded = Math.round(value)
  if (rounded === 0) return '0%'
  return `${rounded > 0 ? '+' : '−'}${Math.abs(rounded)}%`
}

const ROLE_LABEL: Record<string, string> = {
  blank: 'Blank launch',
  unknown: 'No role (plain session)',
  'exec:coordinator': 'Headless coordinator (exec)',
  lane: 'All launched roles (lane)',
}

/** Row label for a cell name: roles keep their launch-table word, launch modes get a plain label. */
export function roleLabel(cell: string): string {
  if (ROLE_LABEL[cell]) return ROLE_LABEL[cell]
  if (cell.startsWith('subagent:')) return cell.slice('subagent:'.length)
  if (cell.startsWith('agent:')) return cell.slice('agent:'.length)
  return cell.charAt(0).toUpperCase() + cell.slice(1)
}

export type CellGroup = 'roles' | 'other' | 'subagents' | 'agents'

export function cellGroup(cell: string): CellGroup {
  if (cell.startsWith('subagent:')) return 'subagents'
  if (cell.startsWith('agent:')) return 'agents'
  if (cell === 'blank' || cell === 'unknown' || cell.startsWith('exec:'))
    return 'other'
  return 'roles'
}

export const GROUP_LABEL: Record<CellGroup, string> = {
  roles: 'Launched roles',
  other: 'Other starts',
  subagents: 'Sub-agents',
  agents: 'Agent Hub agents',
}

export function ageDays(iso: string, now = Date.now()): number {
  return Math.floor((now - new Date(iso).getTime()) / 86_400_000)
}

export function isStale(cell: Pick<MatrixCell, 'latest_at'>, now = Date.now()) {
  return ageDays(cell.latest_at, now) >= STALE_AFTER_DAYS
}

export function cellHref(harness: string, cell: string): string {
  return `/context/cell/${encodeURIComponent(harness)}/${encodeURIComponent(cell)}`
}

export function trendHref(harness: string, role: string, days?: ContextDays) {
  const params = new URLSearchParams({ harness, role })
  if (days && days !== 30) params.set('days', String(days))
  return `/context/trend?${params}`
}

export function flagText(cell: MatrixCell): string | null {
  if (cell.flag === 'warn') {
    return `Over budget: the last 24 h median is ${tok(cell.recent)}, the warn level is ${tok(cell.warn_tokens)}`
  }
  if (cell.flag === 'jump') {
    return `Jumped: the last 24 h median is ${tok(cell.recent)}, at least ${cell.jump_pct ?? '—'}% above the week before`
  }
  return null
}

export function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString([], {
    month: 'short',
    day: 'numeric',
  })
}

export function shortDateTime(iso: string): string {
  const d = new Date(iso)
  return `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '—'
  const secs = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000))
  if (secs < 60) return 'just now'
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86_400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86_400)}d ago`
}

/** Short form of a revision hash such as sha256:5efed5d9…. */
export function shortRevision(revision: string | null): string {
  if (!revision) return '—'
  const bare = revision.includes(':') ? revision.split(':')[1] : revision
  return bare.slice(0, 8)
}

export const PART_COLOR = {
  harness: '#38bdf8',
  ours: '#fbbf24',
  brief: '#94a3b8',
} as const

export const CAUSE_META: Record<string, { label: string; color: string }> = {
  ours: { label: 'Ours', color: '#fbbf24' },
  config: { label: 'Config', color: '#34d399' },
  harness_version: { label: 'Harness version', color: '#a78bfa' },
  harness: { label: 'Harness', color: '#38bdf8' },
  model: { label: 'Model', color: '#fb7185' },
  brief: { label: 'Brief', color: '#94a3b8' },
  none: { label: 'No cause found', color: '#64748b' },
}
