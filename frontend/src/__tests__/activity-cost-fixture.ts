import type { ActivityCost, ActivityTranscript } from '@/lib/api/activity-cost'

const usage = {
  input_tokens: 1000,
  output_tokens: 200,
  cache_read_tokens: 800,
  cache_write_tokens: 20,
  cache_detail_input_tokens: 1000,
}
const transcript: ActivityTranscript = {
  characters: 400,
  argument_characters: 100,
  returned_characters: 300,
  calls_with_returned_text: 7,
  calls_missing_returned_text: 3,
  breakdown: [
    { category: 'substantive', characters: 100, share: 0.25 },
    { category: 'administration', characters: 200, share: 0.5 },
    { category: 'unknown', characters: 100, share: 0.25 },
  ],
}

export const activityFixture: ActivityCost = {
  window_start: '2026-10-21T12:00:00Z',
  window_end: '2026-10-22T12:00:00Z',
  sessions: 4,
  events_sampled: 20,
  event_limit: 20,
  events_truncated: true,
  tools_sampled: 10,
  tools_missing_duration: 3,
  missing_usage_sessions: 1,
  unlinked_sessions: 3,
  unlinked_tokens: 900,
  unlinked_tool_seconds: 75,
  tokens: {
    denominator: 1200,
    unclassified_share: 1,
    sources: [{ source: 'usage_calls', sessions: 3, tokens: 1200 }],
  },
  usage,
  transcript,
  wrappers_excluded: 2,
  unmatched_accounting_tokens: 0,
  unmatched_accounting_calls: 0,
  project_rankings: [
    {
      project_id: 'project/one',
      sessions: 4,
      missing_usage_sessions: 1,
      tokens: 1200,
      usage,
      transcript,
    },
  ],
  project_rankings_total: 1,
  session_rankings: [
    {
      project_id: 'project/one',
      session_id: 's&1',
      provider: 'codex',
      usage_source: 'usage_calls',
      tokens: 1200,
      usage,
      transcript,
    },
  ],
  session_rankings_total: 4,
  tool_time: {
    denominator_seconds: 100,
    explicit_wait_seconds: 10,
    mixed_seconds: 5,
    breakdown: [
      { category: 'substantive', seconds: 25, share: 0.25 },
      { category: 'administration', seconds: 50, share: 0.5 },
      { category: 'unknown', seconds: 25, share: 0.25 },
    ],
  },
  repeat_admin_patterns: [
    {
      family: 'st.context',
      calls: 6,
      sessions: 2,
      measured_tool_seconds: 40,
      projects_total: 2,
      projects: [
        {
          project_id: 'project/one',
          calls: 4,
          sessions: 1,
          measured_tool_seconds: 30,
          sample_session_id: 's&1',
        },
      ],
    },
  ],
  repeat_admin_patterns_total: 8,
  task_rollups: [
    {
      project_id: 'project/one',
      task_id: 'task-real',
      missing_usage_sessions: 0,
      usage,
      transcript,
      sessions: 1,
      tokens: 300,
      sample_session_id: 's&1',
      tool_time: {
        denominator_seconds: 25,
        explicit_wait_seconds: 0,
        mixed_seconds: 0,
        breakdown: [
          { category: 'substantive', seconds: 0, share: 0 },
          { category: 'administration', seconds: 25, share: 1 },
          { category: 'unknown', seconds: 0, share: 0 },
        ],
      },
    },
  ],
  task_rollups_total: 7,
}
