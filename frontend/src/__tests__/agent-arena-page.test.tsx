import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AgentArenaDashboard } from '@/app/agents/[slug]/arena/components/AgentArenaDashboard'
import type { Agent } from '@/app/agents/[slug]/types'
import { createQueryClientWrapper } from './test-utils'

vi.mock('next/navigation', () => ({
  useParams: () => ({ slug: 'persona' }),
  useRouter: () => ({
    push: vi.fn(),
  }),
}))

vi.mock('@/lib/api', () => ({
  fetchAgent: vi.fn(),
  fetchAgentBenchmarkDashboard: vi.fn(),
  fetchAgentMetrics: vi.fn(),
}))

vi.mock('@/app/agents/[slug]/analytics/components/ChartCard', () => ({
  ChartCard: ({
    title,
    children,
  }: {
    title: string
    children: React.ReactNode
  }) => (
    <section>
      <h2>{title}</h2>
      {children}
    </section>
  ),
}))

vi.mock('@/app/agents/[slug]/analytics/components/ChartSection', () => ({
  ChartSection: () => <div>runtime charts</div>,
}))

vi.mock(
  '@/app/agents/[slug]/analytics/components/BenchmarkTrendSection',
  () => ({
    BenchmarkTrendSection: () => <div>benchmark trend</div>,
  }),
)

vi.mock(
  '@/app/agents/[slug]/analytics/components/BenchmarkExperimentSection',
  () => ({
    BenchmarkExperimentSection: ({
      experiments,
    }: {
      experiments: Array<{ experiment_key: string }>
    }) => (
      <div>
        {experiments.length
          ? `experiment ${experiments[0].experiment_key}`
          : 'no experiments'}
      </div>
    ),
  }),
)

vi.mock('@/app/agents/[slug]/analytics/components/KPICard', () => ({
  KPICard: ({ label, value }: { label: string; value: string | number }) => (
    <div>
      <span>{label}</span>
      <span>{String(value)}</span>
    </div>
  ),
}))

import {
  fetchAgent,
  fetchAgentBenchmarkDashboard,
  fetchAgentMetrics,
} from '@/lib/api'

const agent: Agent = {
  id: 1,
  slug: 'persona',
  name: 'Persona',
  description: 'Primary persona',
  system_prompt: 'You are Persona.',
  primary_model_id: 'claude-sonnet-4-6',
  fallback_models: [],
  escalation_model_id: null,
  strategies: {},
  temperature: 0.2,
  thinking_level: 'medium',
  verbosity_level: 'medium',
  is_active: true,
  is_coding_agent: false,
  memory_config: null,
  effective_memory_config: {
    injection_enabled: true,
    project_index_enabled: true,
    tool_capabilities_enabled: true,
    include_mandates: true,
    include_guardrails: true,
    include_references: true,
    reference_index_enabled: true,
    continuity_enabled: true,
    continuity_max_sessions: 5,
    audience_tags: [],
    exclude_tags: [],
    exclude_memory_uuids: [],
  },
  max_concurrency: null,
  max_subagent_concurrency: null,
  daily_token_budget: null,
  hourly_request_limit: null,
  timeout_seconds: 60,
  version: 1,
  created_at: '2026-03-06T13:00:00Z',
  updated_at: '2026-03-06T14:00:00Z',
}

function renderDashboard() {
  return render(<AgentArenaDashboard slug="persona" backHref="/arena" />, {
    wrapper: createQueryClientWrapper(),
  })
}

function emptyBenchmarkDashboard() {
  return {
    agent_slug: 'persona',
    overview: {
      total_runs: 0,
      avg_score: 0,
      pass_rate: 0,
      open_regressions: 0,
      latest_completed_at: null,
      tracked_models: [],
    },
    trend: [],
    recent_runs: [],
    open_regressions: [],
    model_performance: [],
    suites: [],
    cases: [],
    experiments: [],
  }
}

describe('AgentArenaDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchAgent).mockResolvedValue(agent)
  })

  it('keeps the page usable when runtime metrics fail', async () => {
    vi.mocked(fetchAgentMetrics).mockRejectedValue(new Error('metrics offline'))
    vi.mocked(fetchAgentBenchmarkDashboard).mockResolvedValue(
      emptyBenchmarkDashboard(),
    )

    renderDashboard()

    await waitFor(() => {
      expect(
        screen.getByText('Runtime metrics unavailable'),
      ).toBeInTheDocument()
    })

    expect(screen.queryByText('Agent not found')).not.toBeInTheDocument()
  })

  it('shows the empty Arena state when no benchmark history exists', async () => {
    vi.mocked(fetchAgentMetrics).mockResolvedValue({
      slug: 'persona',
      requests_24h: 0,
      avg_latency_ms: 0,
      success_rate: 0,
      tokens_24h: 0,
      cost_24h_usd: 0,
      latency_trend: [],
      success_trend: [],
    })
    vi.mocked(fetchAgentBenchmarkDashboard).mockResolvedValue(
      emptyBenchmarkDashboard(),
    )

    renderDashboard()

    await waitFor(() => {
      expect(
        screen.getByText('Arena is ready for the first benchmark battery.'),
      ).toBeInTheDocument()
    })

    expect(screen.getByText('No recent runtime activity')).toBeInTheDocument()
  })

  it('shows experiments inside Arena instead of a separate analytics page', async () => {
    vi.mocked(fetchAgentMetrics).mockResolvedValue({
      slug: 'persona',
      requests_24h: 4,
      avg_latency_ms: 200,
      success_rate: 100,
      tokens_24h: 4000,
      cost_24h_usd: 0.2,
      latency_trend: Array.from({ length: 24 }, () => 200),
      success_trend: Array.from({ length: 24 }, () => 100),
    })
    vi.mocked(fetchAgentBenchmarkDashboard).mockResolvedValue({
      agent_slug: 'persona',
      overview: {
        total_runs: 3,
        avg_score: 94.2,
        pass_rate: 75,
        open_regressions: 1,
        latest_completed_at: '2026-03-11T12:00:00Z',
        tracked_models: ['codex/gpt-5.4'],
      },
      trend: [
        {
          run_id: 'run-1',
          completed_at: new Date().toISOString(),
          suite_id: 'persona-patience',
          run_kind: 'benchmark',
          avg_score: 94.2,
          pass_rate: 75,
          attempts: 12,
          prompt_version: null,
        },
      ],
      recent_runs: [
        {
          run_id: 'run-1',
          benchmark_id: 'persona-benchmark-aaaa1111',
          suite_id: 'persona-patience',
          run_kind: 'benchmark',
          started_at: '2026-03-11T11:00:00Z',
          completed_at: '2026-03-11T12:00:00Z',
          avg_score: 94.2,
          pass_rate: 75,
          attempt_count: 12,
          passed_attempt_count: 9,
          infra_failure_count: 0,
          models: ['codex/gpt-5.4'],
          case_ids: ['session_patience_quiet'],
          config_snapshot: {},
          metadata: {},
        },
      ],
      open_regressions: [
        {
          regression_key:
            'session_patience_quiet::wrong_fields: should_dispatch',
          suite_id: 'persona-patience',
          case_id: 'session_patience_quiet',
          failure_detail: 'wrong_fields: should_dispatch',
          status: 'open',
          occurrence_count: 2,
          latest_avg_score: 78.8,
          affected_models: ['codex/gpt-5.4'],
          opened_at: '2026-03-11T10:00:00Z',
          last_seen_at: '2026-03-11T12:00:00Z',
          resolved_at: null,
        },
      ],
      model_performance: [
        {
          model_id: 'codex/gpt-5.4',
          attempts: 12,
          avg_score: 94.2,
          pass_rate: 75,
          avg_latency_ms: 1100,
          avg_total_tokens: 1800,
          avg_turns: 4.2,
          avg_tool_calls: 2.3,
          latest_completed_at: '2026-03-11T12:00:00Z',
        },
      ],
      suites: [
        {
          suite_id: 'persona-patience',
          run_count: 3,
          avg_score: 94.2,
          pass_rate: 75,
          open_regressions: 1,
          latest_completed_at: '2026-03-11T12:00:00Z',
          tracked_models: ['codex/gpt-5.4'],
          case_ids: ['session_patience_quiet'],
          run_kinds: ['benchmark'],
        },
      ],
      cases: [
        {
          case_id: 'session_patience_quiet',
          case_name: 'Quiet Session Patience',
          attempts: 12,
          pass_rate: 75,
          avg_score: 94.2,
          open_regressions: 1,
          latest_completed_at: '2026-03-11T12:00:00Z',
          latest_failure_detail: 'wrong_fields: should_dispatch',
          tracked_models: ['codex/gpt-5.4'],
          suite_ids: ['persona-patience'],
        },
      ],
      experiments: [
        {
          experiment_key: 'persona-patience-ab',
          name: 'Persona patience A/B',
          suite_id: 'persona-patience',
          status: 'open',
          decision: 'hold',
          decision_reason: 'underpowered',
          hypothesis: 'Candidate harness should reduce false redispatches.',
          min_runs_per_cohort: 3,
          baseline: {
            label: 'baseline',
            run_count: 2,
            avg_score: 94.2,
            avg_pass_rate: 75,
            avg_total_tokens: 1800,
            avg_turns: 4.0,
            avg_tool_calls: 2.0,
            config_fingerprints: ['abcd1234'],
            config_stable: true,
            prompt_versions: [],
            latest_completed_at: '2026-03-11T12:00:00Z',
          },
          candidate: {
            label: 'candidate',
            run_count: 1,
            avg_score: 95.1,
            avg_pass_rate: 83.3,
            avg_total_tokens: 1700,
            avg_turns: 3.8,
            avg_tool_calls: 1.8,
            config_fingerprints: ['efgh5678'],
            config_stable: true,
            prompt_versions: [],
            latest_completed_at: '2026-03-11T12:05:00Z',
          },
          score_delta: { mean_delta: 0.9, ci_low: -2.0, ci_high: 3.2 },
          pass_rate_delta: { mean_delta: 8.3, ci_low: -16.7, ci_high: 25.0 },
          tool_call_delta: { mean_delta: -0.2, ci_low: -0.6, ci_high: 0.1 },
          updated_at: '2026-03-11T12:05:00Z',
          created_at: '2026-03-11T11:50:00Z',
        },
      ],
    })

    renderDashboard()

    await waitFor(() => {
      expect(screen.getByText('benchmark trend')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Experiments' }))
    expect(
      screen.getByText('experiment persona-patience-ab'),
    ).toBeInTheDocument()
    expect(screen.getByText('Regression watchlist')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Suites' }))
    expect(screen.getByText('Suite board')).toBeInTheDocument()
    expect(screen.getByText('Case watchlist')).toBeInTheDocument()
  })
})
