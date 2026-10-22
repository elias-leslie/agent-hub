import type { ActivityCost } from '@/lib/api/activity-cost'

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
  tokens: { denominator: 1200 },
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
