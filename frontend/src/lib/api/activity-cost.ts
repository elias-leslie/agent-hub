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

export interface ActivityUsage {
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  cache_detail_input_tokens: number
}

export interface ActivityTranscript {
  characters: number
  argument_characters: number
  returned_characters: number
  calls_with_returned_text: number
  calls_missing_returned_text: number
  breakdown: {
    category: ActivityCategory
    characters: number
    share: number | null
  }[]
}

export interface ActivityRanking {
  project_id: string
  tokens: number
  usage: ActivityUsage
  transcript: ActivityTranscript
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
  tokens: {
    denominator: number
    unclassified_share: number | null
    sources: { source: string; sessions: number; tokens: number }[]
  }
  usage: ActivityUsage
  transcript: ActivityTranscript
  wrappers_excluded: number
  unmatched_accounting_tokens: number
  unmatched_accounting_calls: number
  project_rankings: (ActivityRanking & {
    sessions: number
    missing_usage_sessions: number
  })[]
  project_rankings_total: number
  session_rankings: (ActivityRanking & {
    session_id: string
    provider: string
    usage_source: 'cost_logs' | 'usage_calls' | 'response_events' | 'missing'
  })[]
  session_rankings_total: number
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
    missing_usage_sessions: number
    tokens: number
    sample_session_id: string
    tool_time: ToolTime
    usage: ActivityUsage
    transcript: ActivityTranscript
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

function share(value: unknown) {
  return (
    value === null ||
    (typeof value === 'number' &&
      Number.isFinite(value) &&
      value >= 0 &&
      value <= 1)
  )
}
function usage(value: unknown) {
  return (
    record(value) &&
    numbers(value, [
      'input_tokens',
      'output_tokens',
      'cache_read_tokens',
      'cache_write_tokens',
      'cache_detail_input_tokens',
    ]) &&
    Number(value.cache_read_tokens) + Number(value.cache_write_tokens) <=
      Number(value.input_tokens) &&
    Number(value.cache_detail_input_tokens) <= Number(value.input_tokens)
  )
}
function transcript(value: unknown) {
  if (
    !record(value) ||
    !numbers(value, [
      'characters',
      'argument_characters',
      'returned_characters',
      'calls_with_returned_text',
      'calls_missing_returned_text',
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
      !numbers(row, ['characters']) ||
      !share(row.share)
    )
      return false
  }
  return categories.size === 0
}
function ranking(value: unknown) {
  return (
    record(value) &&
    strings(value, ['project_id']) &&
    numbers(value, ['tokens']) &&
    usage(value.usage) &&
    transcript(value.transcript)
  )
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
      'wrappers_excluded',
      'unmatched_accounting_tokens',
      'unmatched_accounting_calls',
      'project_rankings_total',
      'session_rankings_total',
    ]) ||
    typeof value.events_truncated !== 'boolean' ||
    !record(value.tokens) ||
    !numbers(value.tokens, ['denominator']) ||
    !share(value.tokens.unclassified_share) ||
    !Array.isArray(value.tokens.sources) ||
    !value.tokens.sources.every(
      (row) =>
        record(row) &&
        strings(row, ['source']) &&
        numbers(row, ['sessions', 'tokens']),
    ) ||
    !usage(value.usage) ||
    !transcript(value.transcript) ||
    !Array.isArray(value.project_rankings) ||
    !value.project_rankings.every(
      (row) =>
        ranking(row) &&
        record(row) &&
        numbers(row, ['sessions', 'missing_usage_sessions']),
    ) ||
    !Array.isArray(value.session_rankings) ||
    !value.session_rankings.every(
      (row) =>
        ranking(row) &&
        record(row) &&
        strings(row, ['session_id', 'provider']) &&
        ['cost_logs', 'usage_calls', 'response_events', 'missing'].includes(
          String(row.usage_source),
        ),
    ) ||
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
      !numbers(row, ['sessions', 'tokens', 'missing_usage_sessions']) ||
      !usage(row.usage) ||
      !transcript(row.transcript) ||
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
