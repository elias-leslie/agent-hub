import { type ContextSplit, isContextSplit } from './context-split'
import {
  type DurationSplit,
  isDurationSplit,
  isWorkRoleOption,
  type WorkRoleOption,
} from './duration-split'

/** Recorded usage and separate, explicitly estimated ST text footprint. */
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

export type HunterResponseCategory =
  | 'investigation_only'
  | 'mixed'
  | 'support_coordination'
  | 'unknown'

export interface HunterResponseMetrics {
  responses: number
  tokens: number
  usage: ActivityUsage
  breakdown: {
    category: HunterResponseCategory
    responses: number
    response_share: number | null
    tokens: number
    token_share: number | null
  }[]
}

export interface HunterResponseActivity extends HunterResponseMetrics {
  method: 'linked-provider-responses-v1'
  sessions_total: number
  sessions_without_usage: number
  duplicate_usage_events: number
  unusable_usage_events: number
  tools_without_response: number
  events_truncated: boolean
  basis: string
  rows: (HunterResponseMetrics & {
    session_id: string
    project_id: string
    harness: string
    work_role: string
    tools_without_response: number
    window_starts_mid_session: boolean
    first_source_recon_signal: {
      action: 'source_read' | 'source_search' | 'recon_run'
      sample_response_number: number | null
      seconds_from_first_response: number | null
      input_tokens: number | null
    } | null
    input_per_response: {
      first_tokens: number | null
      peak_tokens: number | null
      peak_sample_response_number: number | null
    }
  })[]
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

export interface StCommandMetrics {
  commands: number
  measured_seconds: number
  input_tokens_estimate: number
  output_tokens_estimate: number
  commands_with_tokenized_input: number
  commands_with_duration: number
  commands_with_output: number
  shared_commands: number
}

export interface StCommandSummary extends StCommandMetrics {
  input_token_encoding: string
  output_characters_per_token: number
  shell_calls: number
  shell_calls_unparsed: number
  calls_with_st: number
  unknown_commands: number
  administration_commands: number
  substantive_commands: number
  families_total: number
  families: (StCommandMetrics & {
    family: string
    category: ActivityCategory | 'necessary_support'
    sample_session_id: string | null
    sample_project_id: string | null
  })[]
}

export type EfficiencyStatus =
  | 'within_goal'
  | 'above_goal'
  | 'insufficient_coverage'
  | 'unmeasured'
  | 'goal_not_selected'

export interface SessionEfficiencyData {
  method: 'session-tool-occupancy-v1'
  goal: {
    admin_share_target: number | null
    minimum_duration_coverage: number
    maximum_unknown_share: number
  }
  trial_goal: { relative_cost_reduction_target: number }
  sessions_total: number
  status_counts: Record<EfficiencyStatus, number>
  rows: (ActivityRanking & {
    context_split?: ContextSplit
    session_id: string
    provider: string
    model: string | null
    usage_source: string
    tool_time: ToolTime
    tools_sampled: number
    tools_missing_duration: number
    sampled_event_span_seconds: number | null
    goal_status: EfficiencyStatus
    repeat_admin_patterns_total: number
    repeat_admin_patterns: {
      family: string
      calls: number
      measured_tool_seconds: number
    }[]
  })[]
}

export interface ActivityCost {
  hunter_responses?: HunterResponseActivity
  context_split?: ContextSplit
  duration_split?: DurationSplit
  by_project?: (ActivityComparison & { project_id: string })[]
  by_work_role?: (ActivityComparison & { work_role_id: string })[]
  by_harness?: (ActivityComparison & { harness_id: string })[]
  work_roles?: WorkRoleOption[]
  harnesses?: WorkRoleOption[]
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
  st_commands?: StCommandSummary | null
  session_efficiency?: SessionEfficiencyData | null
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

export interface ActivityComparison {
  context_split?: ContextSplit
  label: string
  sessions: number
  duration_split: DurationSplit
  usage?: ActivityUsage
  cost?: {
    recorded_calls: number
    api_equiv_known_calls: number
    cash_known_calls: number
    api_equiv_usd: number | null
    cash_usd: number | null
  }
  coverage?: { usage_sessions: number; missing_usage_sessions: number }
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

function hunterResponseMetrics(value: unknown) {
  if (
    !record(value) ||
    !numbers(value, ['responses', 'tokens']) ||
    !usage(value.usage) ||
    !Array.isArray(value.breakdown)
  )
    return false
  const categories = new Set([
    'investigation_only',
    'mixed',
    'support_coordination',
    'unknown',
  ])
  let responses = 0
  let tokens = 0
  for (const row of value.breakdown) {
    if (
      !record(row) ||
      typeof row.category !== 'string' ||
      !categories.delete(row.category) ||
      !numbers(row, ['responses', 'tokens']) ||
      !share(row.response_share) ||
      !share(row.token_share)
    )
      return false
    responses += Number(row.responses)
    tokens += Number(row.tokens)
  }
  return (
    categories.size === 0 &&
    responses === value.responses &&
    tokens === value.tokens &&
    record(value.usage) &&
    tokens ===
      Number(value.usage.input_tokens) + Number(value.usage.output_tokens)
  )
}

function nullableNumbers(row: Record<string, unknown>, keys: string[]) {
  return keys.every((key) => row[key] === null || numbers(row, [key]))
}

function hunterResponses(value: unknown) {
  if (value === undefined) return true
  return (
    record(value) &&
    value.method === 'linked-provider-responses-v1' &&
    hunterResponseMetrics(value) &&
    strings(value, ['basis']) &&
    numbers(value, [
      'sessions_total',
      'sessions_without_usage',
      'duplicate_usage_events',
      'unusable_usage_events',
      'tools_without_response',
    ]) &&
    Number(value.sessions_without_usage) <= Number(value.sessions_total) &&
    typeof value.events_truncated === 'boolean' &&
    Array.isArray(value.rows) &&
    value.rows.length <= Number(value.sessions_total) &&
    value.rows.every(
      (row: unknown) =>
        record(row) &&
        hunterResponseMetrics(row) &&
        strings(row, ['session_id', 'project_id', 'harness', 'work_role']) &&
        numbers(row, ['tools_without_response']) &&
        typeof row.window_starts_mid_session === 'boolean' &&
        record(row.input_per_response) &&
        nullableNumbers(row.input_per_response, [
          'first_tokens',
          'peak_tokens',
          'peak_sample_response_number',
        ]) &&
        (row.first_source_recon_signal === null ||
          (record(row.first_source_recon_signal) &&
            ['source_read', 'source_search', 'recon_run'].includes(
              String(row.first_source_recon_signal.action),
            ) &&
            nullableNumbers(row.first_source_recon_signal, [
              'sample_response_number',
              'seconds_from_first_response',
              'input_tokens',
            ]))),
    )
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

function stMetrics(value: unknown) {
  return (
    record(value) &&
    numbers(value, [
      'commands',
      'measured_seconds',
      'input_tokens_estimate',
      'output_tokens_estimate',
      'commands_with_tokenized_input',
      'commands_with_duration',
      'commands_with_output',
      'shared_commands',
    ]) &&
    Number(value.commands_with_tokenized_input) <= Number(value.commands) &&
    Number(value.commands_with_duration) + Number(value.shared_commands) <=
      Number(value.commands) &&
    Number(value.commands_with_output) + Number(value.shared_commands) <=
      Number(value.commands)
  )
}

function stCommands(value: unknown) {
  if (value == null) return true // Older servers have no ST-specific coverage.
  return (
    record(value) &&
    stMetrics(value) &&
    numbers(value, [
      'shell_calls',
      'shell_calls_unparsed',
      'calls_with_st',
      'unknown_commands',
      'administration_commands',
      'substantive_commands',
      'families_total',
      'output_characters_per_token',
    ]) &&
    strings(value, ['input_token_encoding']) &&
    Number(value.output_characters_per_token) > 0 &&
    Number(value.shell_calls_unparsed) + Number(value.calls_with_st) <=
      Number(value.shell_calls) &&
    Number(value.unknown_commands) <= Number(value.commands) &&
    Number(value.administration_commands) +
      Number(value.substantive_commands) +
      Number(value.unknown_commands) ===
      Number(value.commands) &&
    Array.isArray(value.families) &&
    value.families.length <= Number(value.families_total) &&
    value.families.every(
      (row: unknown) =>
        record(row) &&
        stMetrics(row) &&
        strings(row, ['family']) &&
        [
          'substantive',
          'administration',
          'necessary_support',
          'unknown',
        ].includes(String(row.category)) &&
        ((row.sample_session_id === null && row.sample_project_id === null) ||
          strings(row, ['sample_session_id', 'sample_project_id'])),
    )
  )
}

function sessionEfficiency(value: unknown) {
  if (value == null) return true
  const statuses = [
    'within_goal',
    'above_goal',
    'insufficient_coverage',
    'unmeasured',
    'goal_not_selected',
  ]
  return (
    record(value) &&
    value.method === 'session-tool-occupancy-v1' &&
    record(value.goal) &&
    share(value.goal.admin_share_target) &&
    typeof value.goal.minimum_duration_coverage === 'number' &&
    share(value.goal.minimum_duration_coverage) &&
    typeof value.goal.maximum_unknown_share === 'number' &&
    share(value.goal.maximum_unknown_share) &&
    record(value.trial_goal) &&
    typeof value.trial_goal.relative_cost_reduction_target === 'number' &&
    share(value.trial_goal.relative_cost_reduction_target) &&
    numbers(value, ['sessions_total']) &&
    record(value.status_counts) &&
    numbers(value.status_counts, statuses) &&
    Object.values(value.status_counts).reduce<number>(
      (sum, count) => sum + Number(count),
      0,
    ) === value.sessions_total &&
    Array.isArray(value.rows) &&
    value.rows.length <= Number(value.sessions_total) &&
    value.rows.every(
      (row: unknown) =>
        record(row) &&
        ranking(row) &&
        strings(row, ['session_id', 'provider', 'usage_source']) &&
        (row.model === null || typeof row.model === 'string') &&
        toolTime(row.tool_time) &&
        (row.context_split === undefined ||
          isContextSplit(row.context_split)) &&
        numbers(row, [
          'tools_sampled',
          'tools_missing_duration',
          'repeat_admin_patterns_total',
        ]) &&
        Number(row.tools_missing_duration) <= Number(row.tools_sampled) &&
        (row.sampled_event_span_seconds === null ||
          numbers(row, ['sampled_event_span_seconds'])) &&
        statuses.includes(String(row.goal_status)) &&
        Array.isArray(row.repeat_admin_patterns) &&
        row.repeat_admin_patterns.length <=
          Number(row.repeat_admin_patterns_total) &&
        row.repeat_admin_patterns.every(
          (family: unknown) =>
            record(family) &&
            strings(family, ['family']) &&
            numbers(family, ['calls', 'measured_tool_seconds']),
        ),
    )
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
    !stCommands(value.st_commands) ||
    !sessionEfficiency(value.session_efficiency) ||
    !hunterResponses(value.hunter_responses) ||
    !activityComparisons(value) ||
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

function activityComparisons(value: Record<string, unknown>): boolean {
  if (value.context_split !== undefined && !isContextSplit(value.context_split))
    return false
  if (
    value.duration_split !== undefined &&
    !isDurationSplit(value.duration_split)
  )
    return false
  for (const key of ['work_roles', 'harnesses']) {
    if (
      value[key] !== undefined &&
      (!Array.isArray(value[key]) || !value[key].every(isWorkRoleOption))
    )
      return false
  }
  for (const [key, id] of [
    ['by_project', 'project_id'],
    ['by_work_role', 'work_role_id'],
    ['by_harness', 'harness_id'],
  ]) {
    const rows = value[key]
    if (rows === undefined) continue
    if (
      !Array.isArray(rows) ||
      !rows.every(
        (row: unknown) =>
          record(row) &&
          strings(row, [id, 'label']) &&
          numbers(row, ['sessions']) &&
          isDurationSplit(row.duration_split) &&
          (row.context_split === undefined ||
            isContextSplit(row.context_split)) &&
          (row.usage === undefined || usage(row.usage)) &&
          (row.coverage === undefined ||
            (record(row.coverage) &&
              numbers(row.coverage, [
                'usage_sessions',
                'missing_usage_sessions',
              ]))) &&
          (row.cost === undefined ||
            (record(row.cost) &&
              numbers(row.cost, [
                'recorded_calls',
                'api_equiv_known_calls',
                'cash_known_calls',
              ]) &&
              ['api_equiv_usd', 'cash_usd'].every(
                (key) =>
                  row.cost !== null &&
                  record(row.cost) &&
                  (row.cost[key] === null || numbers(row.cost, [key])),
              ) &&
              Number(row.cost.api_equiv_known_calls) <=
                Number(row.cost.recorded_calls) &&
              Number(row.cost.cash_known_calls) <=
                Number(row.cost.recorded_calls))),
      )
    )
      return false
  }
  return true
}

export function activitySessionParams(
  activity: Pick<ActivityCost, 'window_start' | 'window_end'>,
  scope?: URLSearchParams,
): URLSearchParams {
  const params = new URLSearchParams(
    scope ?? { kind: 'all', subagents: '1', benchmarks: '1', since: 'all' },
  )
  params.set('accounting_start', activity.window_start)
  params.set('accounting_end', activity.window_end)
  return params
}

export function activitySessionsHref(
  project?: string,
  session?: string,
  scope?: URLSearchParams,
): string {
  const params = new URLSearchParams(
    scope ?? {
      kind: 'all',
      subagents: '1',
      benchmarks: '1',
      since: 'all',
    },
  )
  if (project) params.set('project', project)
  if (session) params.set('sel', session)
  return `/sessions?${params.toString()}`
}
