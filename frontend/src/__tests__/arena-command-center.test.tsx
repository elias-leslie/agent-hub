import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ArenaCommandCenter } from '@/app/arena/components/ArenaCommandCenter'
import { createQueryClientWrapper } from './test-utils'

vi.mock('@/lib/api', () => ({
  fetchArenaOverview: vi.fn(),
}))

vi.mock('@/lib/api/persona', () => ({
  PERSONA_QUERY_KEY: ['persona'],
  fetchPersona: vi.fn(),
}))

import { fetchArenaOverview } from '@/lib/api'
import { fetchPersona } from '@/lib/api/persona'

function renderCommandCenter() {
  return render(<ArenaCommandCenter />, { wrapper: createQueryClientWrapper() })
}

describe('ArenaCommandCenter', () => {
  it('shows autonomy and memory pulse from the overview payload', async () => {
    vi.mocked(fetchPersona).mockResolvedValue({
      id: 1,
      name: 'Astra',
    } as never)
    vi.mocked(fetchArenaOverview).mockResolvedValue({
      generated_at: '2026-03-22T15:30:00Z',
      project_id: 'agent-hub',
      primary_agent_slug: 'persona',
      days: 30,
      system: {
        total_agents: 2,
        agents_with_history: 1,
        total_runs: 12,
        avg_score: 91.2,
        avg_pass_rate: 77,
        total_regressions: 3,
        regressions_by_category: { behavior: 3 },
      },
      scheduled_jobs: [
        {
          id: 'job-review',
          name: 'Daily Persona Improvement Review',
          payload_type: 'agent_turn',
          enabled: true,
          last_run_at: null,
          next_run_at: '2026-03-23T09:00:00Z',
          run_count: 0,
        },
        {
          id: 'job-honing',
          name: 'Nightly Persona Self-Honing',
          payload_type: 'self_honing',
          enabled: true,
          last_run_at: null,
          next_run_at: '2026-03-23T09:30:00Z',
          run_count: 0,
        },
      ],
      agent_signal_volume: [
        {
          agent_slug: 'persona',
          friction: 2,
          improvement: 1,
          idea: 0,
          praise: 0,
          system: 2,
        },
      ],
      repeated_issues: [
        {
          agent_slug: 'persona',
          feedback_type: 'friction',
          content: 'missed rebuild.sh before verification',
          count: 2,
          latest_at: '2026-03-22T15:00:00Z',
        },
      ],
      recent_benchmark_experiments: [
        {
          suite_id: 'persona-suite',
          decision: 'hold',
          decision_reason: 'underpowered',
          score_delta: -0.5,
          pass_rate_delta: 0,
        },
      ],
      open_regression_clusters: [
        {
          case_id: 'rebuild_rule_reconsideration',
          occurrence_count: 3,
          failure_detail: 'forgot rebuild.sh',
          failure_kind: 'model',
          failure_category: 'behavior',
          last_seen_at: '2026-03-22T15:00:00Z',
        },
      ],
      memory_utilization: {
        injection_sessions: 4,
        citation_sessions: 2,
        lookup_after_injection_sessions: 2,
        citation_session_rate: 0.5,
        assistant_citation_rate: 0.5,
        selected_reference_citation_rate: 0.333,
        memory_search_calls: 5,
        memory_get_calls: 1,
        memory_debug_coverage_rate: 1,
      },
      memory_governance: {
        active_count: 18,
        active_agent_count: 2,
        health_status: 'warn',
        by_context_kind: { policy: 7, reference: 11 },
        targeted_count: 4,
        explicit_exclusion_count: 1,
        untargeted_reference_count: 7,
        policy_with_targeting_count: 0,
        missing_reference_summary_count: 2,
        missing_capability_summary_count: 0,
        oversized_policy_count: 1,
        alias_trigger_task_type_count: 1,
        startup_profile_agent_target_count: 0,
        invalid_trigger_task_type_count: 1,
        custom_memory_config_agent_count: 1,
        project_index_disabled_agent_count: 0,
        tool_capabilities_disabled_agent_count: 1,
        reference_index_disabled_agent_count: 0,
        memory_exclusion_agent_count: 1,
        excluded_memory_uuid_count: 2,
        invalid_trigger_task_type_samples: [
          {
            uuid: 'ref-3',
            label: 'outdated trigger',
            details: 'invalid trigger types: security',
            load_count: 3,
            invalid_types: ['security'],
          },
        ],
        untargeted_reference_samples: [],
        oversized_policy_samples: [],
        startup_profile_agent_target_samples: [],
        hard_issue_count: 1,
        soft_issue_count: 3,
        soft_limit_breach_count: 0,
        issue_count: 4,
      },
      low_yield_references: [
        {
          uuid: 'ref-2',
          label: 'noisy-ref',
          selected: 2,
          cited: 0,
          citation_rate: 0,
          tags: ['debugger-relevant'],
        },
      ],
      agents: [
        {
          slug: 'persona',
          name: 'Astra',
          description: 'Primary persona',
          benchmark: {
            total_runs: 12,
            avg_score: 91.2,
            pass_rate: 77,
            open_regressions: 3,
            latest_completed_at: '2026-03-22T12:00:00Z',
          },
          signal_volume: {
            agent_slug: 'persona',
            friction: 2,
            improvement: 1,
            idea: 0,
            praise: 0,
            system: 2,
          },
          top_issue: {
            agent_slug: 'persona',
            feedback_type: 'friction',
            content: 'missed rebuild.sh before verification',
            count: 2,
            latest_at: '2026-03-22T15:00:00Z',
          },
        },
        {
          slug: 'debugger',
          name: 'Debugger',
          description: 'Debug specialist',
          benchmark: {
            total_runs: 0,
            avg_score: null,
            pass_rate: null,
            open_regressions: 0,
            latest_completed_at: null,
          },
          signal_volume: null,
          top_issue: null,
        },
      ],
    })

    renderCommandCenter()

    await waitFor(() => {
      expect(screen.getByText('Astra + Agent Pulse')).toBeInTheDocument()
    })

    expect(screen.getByText('Daily review')).toBeInTheDocument()
    expect(screen.getByText('Nightly honing')).toBeInTheDocument()
    expect(screen.getByText('Memory health')).toBeInTheDocument()
    expect(screen.getByText('1 benchmarked')).toBeInTheDocument()
    expect(
      screen.getByText('Experiment + regression pulse'),
    ).toBeInTheDocument()
    expect(screen.getByText('Memory watchlist')).toBeInTheDocument()
    expect(screen.getByText('Memory governance')).toBeInTheDocument()
    expect(screen.getByText('Agent delivery controls')).toBeInTheDocument()
    expect(screen.getByText('outdated trigger')).toBeInTheDocument()
    expect(screen.getAllByText('behavior')).toHaveLength(1)
    expect(
      screen.getAllByText('missed rebuild.sh before verification'),
    ).toHaveLength(2)
    expect(screen.getByText('noisy-ref')).toBeInTheDocument()
    expect(screen.getByText('Astra')).toBeInTheDocument()
    expect(screen.getByText('Debugger')).toBeInTheDocument()
  })
})
