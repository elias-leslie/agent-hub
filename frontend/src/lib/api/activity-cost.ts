/** Recorded observations only; no allocation of time or tokens to individual commands. */
export type ActivityCategory = 'substantive' | 'administration' | 'unknown'

export interface ToolTime {
  denominator_seconds: number
  explicit_wait_seconds: number
  mixed_seconds: number
  breakdown: {
    category: ActivityCategory
    seconds: number
    share: number | null
  }[]
}

export interface ActivityProject {
  project_id: string
  calls: number
  sessions: number
  measured_tool_seconds: number
  sample_session_id: string
}

export interface ActivityCost {
  window_start: string
  window_end: string
  sessions: number
  events_sampled: number
  event_limit: number
  events_truncated: boolean
  tools_sampled: number
  tools_missing_duration: number
  missing_usage_sessions: number
  unlinked_sessions: number
  unlinked_tokens: number
  unlinked_tool_seconds: number
  tokens: { denominator: number }
  tool_time: ToolTime
  repeat_admin_patterns: {
    family: string
    calls: number
    sessions: number
    measured_tool_seconds: number
    projects: ActivityProject[]
    projects_total: number
  }[]
  repeat_admin_patterns_total: number
  task_rollups: {
    project_id: string
    task_id: string
    sessions: number
    tokens: number
    sample_session_id: string
    tool_time: ToolTime
  }[]
  task_rollups_total: number
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function numbers(row: Record<string, unknown>, keys: string[]) {
  return keys.every(
    (key) =>
      typeof row[key] === 'number' &&
      Number.isFinite(row[key]) &&
      row[key] >= 0,
  )
}
function strings(row: Record<string, unknown>, keys: string[]) {
  return keys.every(
    (key) => typeof row[key] === 'string' && row[key].length > 0,
  )
}
function toolTime(value: unknown) {
  if (
    !record(value) ||
    !numbers(value, [
      'denominator_seconds',
      'explicit_wait_seconds',
      'mixed_seconds',
    ]) ||
    !Array.isArray(value.breakdown)
  )
    return false
  const categories = new Set(['substantive', 'administration', 'unknown'])
  for (const row of value.breakdown) {
    if (
      !record(row) ||
      typeof row.category !== 'string' ||
      !categories.delete(row.category) ||
      !numbers(row, ['seconds']) ||
      !(
        row.share === null ||
        (typeof row.share === 'number' &&
          Number.isFinite(row.share) &&
          row.share >= 0 &&
          row.share <= 1)
      )
    )
      return false
  }
  return categories.size === 0
}

/** A missing older-server field is unavailable, never a fabricated zero. */
export function parseActivityCost(value: unknown): ActivityCost | null {
  if (value == null) return null
  if (
    !record(value) ||
    !strings(value, ['window_start', 'window_end']) ||
    !Number.isFinite(Date.parse(String(value.window_start))) ||
    !Number.isFinite(Date.parse(String(value.window_end))) ||
    !numbers(value, [
      'sessions',
      'events_sampled',
      'event_limit',
      'tools_sampled',
      'tools_missing_duration',
      'missing_usage_sessions',
      'unlinked_sessions',
      'unlinked_tokens',
      'unlinked_tool_seconds',
      'repeat_admin_patterns_total',
      'task_rollups_total',
    ]) ||
    typeof value.events_truncated !== 'boolean' ||
    !record(value.tokens) ||
    !numbers(value.tokens, ['denominator']) ||
    !toolTime(value.tool_time) ||
    !Array.isArray(value.repeat_admin_patterns) ||
    !Array.isArray(value.task_rollups)
  )
    throw new Error('Activity data is incomplete or invalid')
  for (const row of value.repeat_admin_patterns) {
    if (
      !record(row) ||
      !strings(row, ['family']) ||
      !numbers(row, [
        'calls',
        'sessions',
        'measured_tool_seconds',
        'projects_total',
      ]) ||
      !Array.isArray(row.projects) ||
      !row.projects.every(
        (project) =>
          record(project) &&
          strings(project, ['project_id', 'sample_session_id']) &&
          numbers(project, ['calls', 'sessions', 'measured_tool_seconds']),
      )
    )
      throw new Error('Activity family data is incomplete or invalid')
  }
  for (const row of value.task_rollups) {
    if (
      !record(row) ||
      !strings(row, ['project_id', 'task_id', 'sample_session_id']) ||
      !numbers(row, ['sessions', 'tokens']) ||
      !toolTime(row.tool_time)
    )
      throw new Error('Activity task data is incomplete or invalid')
  }
  return value as unknown as ActivityCost
}

export function activitySessionsHref(
  project?: string,
  session?: string,
): string {
  const params = new URLSearchParams({
    kind: 'all',
    subagents: '1',
    benchmarks: '1',
    since: 'all',
  })
  if (project) params.set('project', project)
  if (session) params.set('sel', session)
  return `/sessions?${params.toString()}`
}
