import type { SpendKind, SpendRange } from '@/lib/api/analytics'

export const KIND_META: Record<
  SpendKind,
  { label: string; hint: string; color: string; dot: string }
> = {
  interactive: {
    label: 'Interactive',
    hint: 'Sessions where you work with an agent',
    color: '#38bdf8',
    dot: 'bg-sky-400',
  },
  routine: {
    label: 'Routine',
    hint: 'Scheduled and scripted runs',
    color: '#fbbf24',
    dot: 'bg-amber-400',
  },
  other: {
    label: 'Other',
    hint: 'Completions and work with no known origin',
    color: '#94a3b8',
    dot: 'bg-slate-400',
  },
}

export const KIND_ORDER: SpendKind[] = ['interactive', 'routine', 'other']

export const RANGE_LABEL: Record<SpendRange, string> = {
  '1h': 'last hour',
  '24h': 'last 24 hours',
  '7d': 'last 7 days',
  '30d': 'last 30 days',
}

/** Days of plan accounting that best match a chart range. */
export const RANGE_DAYS: Record<SpendRange, number> = {
  '1h': 1,
  '24h': 1,
  '7d': 7,
  '30d': 30,
}

export const SOURCE_LABEL: Record<string, string> = {
  claude_code: 'Claude Code',
  agent: 'Codex',
  completion: 'completion',
}

export function usd(value: number): string {
  if (value === 0) return '$0'
  if (value < 0.01) return '<$0.01'
  if (value >= 1000) return `$${Math.round(value).toLocaleString()}`
  if (value >= 100) return `$${value.toFixed(0)}`
  return `$${value.toFixed(2)}`
}

export function tokens(value: number): string {
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)}B`
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`
  if (value >= 1e3) return `${(value / 1e3).toFixed(0)}K`
  return String(value)
}

export function share(value: number): string {
  const pct = value * 100
  if (pct > 0 && pct < 1) return '<1%'
  return `${Math.round(pct)}%`
}

/** Label for a chart bar's start, sized to the range's bucket. */
export function bucketLabel(iso: string, range: SpendRange): string {
  const d = new Date(iso)
  if (range === '1h' || range === '24h') {
    return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  }
  if (range === '7d') {
    return `${d.toLocaleDateString([], { weekday: 'short' })} ${d.toLocaleTimeString([], { hour: 'numeric' })}`
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

export function bucketSpan(
  iso: string,
  seconds: number,
  range: SpendRange,
): string {
  const end = new Date(new Date(iso).getTime() + seconds * 1000).toISOString()
  return `${bucketLabel(iso, range)} to ${bucketLabel(end, range)}`
}
