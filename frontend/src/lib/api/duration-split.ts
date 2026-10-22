import { type ContextSplit, isContextSplit } from './context-split'

/** Recorded non-wait tool occupancy, shared by Activity and Sessions. */
export interface DurationSplit {
  context_split?: ContextSplit | null
  admin_seconds: number
  other_seconds: number
  denominator_seconds: number
  admin_share: number | null
  other_share: number | null
  unknown_seconds: number
  unknown_share: number | null
  tools_sampled: number
  tools_missing_duration: number
  duration_coverage: number | null
  events_truncated: boolean
}

export interface AccountingWindow {
  start: string
  end: string
}

export interface WorkRoleOption {
  id: string
  label: string
}

export interface SessionWorkRole extends WorkRoleOption {
  source: string
  declared_at: string
  display_name?: string | null
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function isAccountingWindow(value: unknown): value is AccountingWindow {
  return (
    isRecord(value) &&
    typeof value.start === 'string' &&
    typeof value.end === 'string' &&
    Number.isFinite(Date.parse(value.start)) &&
    Number.isFinite(Date.parse(value.end)) &&
    Date.parse(value.start) < Date.parse(value.end)
  )
}

export function isWorkRoleOption(value: unknown): value is WorkRoleOption {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    value.id.length > 0 &&
    typeof value.label === 'string' &&
    value.label.length > 0
  )
}

export function isSessionWorkRole(value: unknown): value is SessionWorkRole {
  return (
    isWorkRoleOption(value) &&
    isRecord(value) &&
    typeof value.source === 'string' &&
    value.source.length > 0 &&
    typeof value.declared_at === 'string' &&
    Number.isFinite(Date.parse(value.declared_at)) &&
    (value.display_name == null || typeof value.display_name === 'string')
  )
}

export function isDurationSplit(value: unknown): value is DurationSplit {
  if (
    !isRecord(value) ||
    (value.context_split != null && !isContextSplit(value.context_split))
  )
    return false
  const counts = ['tools_sampled', 'tools_missing_duration']
  const durations = [
    'admin_seconds',
    'other_seconds',
    'denominator_seconds',
    'unknown_seconds',
  ]
  if (
    ![...counts, ...durations].every(
      (key) =>
        typeof value[key] === 'number' &&
        Number.isFinite(value[key]) &&
        value[key] >= 0,
    ) ||
    !counts.every((key) => Number.isInteger(value[key])) ||
    Number(value.tools_missing_duration) > Number(value.tools_sampled) ||
    typeof value.events_truncated !== 'boolean'
  )
    return false
  for (const key of [
    'admin_share',
    'other_share',
    'unknown_share',
    'duration_coverage',
  ]) {
    const share = value[key]
    if (
      share !== null &&
      !(
        typeof share === 'number' &&
        Number.isFinite(share) &&
        share >= 0 &&
        share <= 1
      )
    )
      return false
  }
  if (value.denominator_seconds === 0)
    return (
      value.admin_share === null &&
      value.other_share === null &&
      value.unknown_share === null
    )
  return (
    value.admin_share !== null &&
    value.other_share !== null &&
    value.unknown_share !== null
  )
}

export const durationPercent = (value: number | null | undefined) =>
  value == null ? 'Unavailable' : `${(value * 100).toFixed(1)}%`

export function durationSeconds(value: number): string {
  return `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })}s`
}
