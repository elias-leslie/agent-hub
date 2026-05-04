import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { UnifiedPersonaWorkspace } from '@/app/persona/components/UnifiedPersonaWorkspace'

const mockFetchPersonaStream = vi.fn()
const mockUseChatStream = vi.fn()
const mockFetchSessionEvents = vi.fn()

function buildPulseFields(
  overrides?: Partial<{
    issue_markers: Array<{
      event_id: string
      event_type: string
      created_at: string
      tool_name: string | null
      tags: string[]
      primary_tag: string
      root_causes: string[]
      primary_root_cause: string | null
      title: string
      summary: string
      detail: string | null
      fingerprint: string | null
    }>
    pulse_tags: string[]
    primary_pulse_tag: string | null
    root_causes: string[]
    primary_root_cause: string | null
    pulse_summary: string | null
  }>,
) {
  return {
    issue_markers: [],
    pulse_tags: [],
    primary_pulse_tag: null,
    root_causes: [],
    primary_root_cause: null,
    pulse_summary: null,
    ...overrides,
  }
}

function buildStreamResponse(options?: {
  heartbeatStatus?: 'active' | 'completed'
  heartbeatLiveStatus?: string | null
  includeSecondHeartbeat?: boolean
}) {
  const longToolFrictionSummary =
    'git status --short --branch && st context task-123 && st done task-123 --message "Verified autocode completion; quality gate passed." after repeated retries before success.'
  const heartbeatStatus = options?.heartbeatStatus ?? 'completed'
  const heartbeatLiveStatus = options?.heartbeatLiveStatus ?? null
  const entries = [
    {
      id: 'm-1',
      entry_type: 'message',
      timestamp: '2026-03-09T10:00:00Z',
      session_id: 'chat-1',
      parent_session_id: null,
      project_id: 'persona-sandbox',
      agent_slug: 'persona',
      session_type: 'chat',
      status: 'completed',
      role: 'user',
      content: 'pause that task',
      summary_oneliner: null,
      display_summary: null,
      current_branch: null,
      external_id: null,
      model: 'claude-sonnet',
      live_summary: null,
      live_status: null,
      message_count: 2,
      tool_count: 0,
      event_previews: [],
      ...buildPulseFields(),
    },
    {
      id: 'h-1',
      entry_type: 'heartbeat',
      timestamp: '2026-03-09T10:01:00Z',
      session_id: 'hb-1',
      parent_session_id: null,
      project_id: 'persona-sandbox',
      agent_slug: 'persona',
      session_type: 'heartbeat',
      status: heartbeatStatus,
      role: null,
      content: null,
      summary_oneliner: 'Checked active work',
      display_summary:
        'Checked active work across queue, cleanup, and session truth. Dispatched the next safe follow-up lane.',
      current_branch: null,
      external_id: null,
      model: 'claude-sonnet',
      live_summary: heartbeatStatus === 'active' ? 'Running validation' : null,
      live_status: heartbeatLiveStatus,
      message_count: 0,
      tool_count: 3,
      event_previews: [
        {
          id: 'preview-h-1',
          event_type: 'tool_use',
          created_at: '2026-03-09T10:01:10Z',
          role: null,
          tool_name: 'st ready-all',
          content_preview: null,
          tool_input_preview: '{"project":"agent-hub"}',
          tool_output_preview: null,
          duration_ms: null,
          model_used: 'claude-sonnet',
        },
      ],
      ...buildPulseFields({
        issue_markers: [
          {
            event_id: 'preview-h-issue',
            event_type: 'assistant_message',
            created_at: '2026-03-09T10:01:20Z',
            tool_name: null,
            tags: ['warning'],
            primary_tag: 'warning',
            root_causes: ['context'],
            primary_root_cause: 'context',
            title: 'Completed with warnings',
            summary: 'The run finished but still needed follow-up.',
            detail: 'The run finished but still needed follow-up.',
            fingerprint: 'warning:context',
          },
        ],
        pulse_tags: ['friction', 'warning', 'recovered'],
        primary_pulse_tag: 'warning',
        root_causes: ['context'],
        primary_root_cause: 'context',
        pulse_summary: 'completed with warnings; recovered before completion',
      }),
    },
    ...(options?.includeSecondHeartbeat
      ? [
          {
            id: 'h-2',
            entry_type: 'heartbeat',
            timestamp: '2026-03-09T10:03:00Z',
            session_id: 'hb-2',
            parent_session_id: null,
            project_id: 'persona-sandbox',
            agent_slug: 'persona',
            session_type: 'heartbeat',
            status: 'completed',
            role: null,
            content: null,
            summary_oneliner: 'Checked backlog state',
            display_summary:
              'Checked backlog state across open tasks and cleanup debt.',
            current_branch: null,
            external_id: null,
            model: 'claude-sonnet',
            live_summary: null,
            live_status: null,
            message_count: 0,
            tool_count: 1,
            event_previews: [
              {
                id: 'preview-h-2',
                event_type: 'tool_result',
                created_at: '2026-03-09T10:03:10Z',
                role: null,
                tool_name: 'st ready-all',
                content_preview: 'No additional work',
                tool_input_preview: null,
                tool_output_preview: '{"status":"ok"}',
                duration_ms: 800,
                model_used: 'claude-sonnet',
              },
            ],
            ...buildPulseFields(),
          },
        ]
      : []),
    {
      id: 'c-1',
      entry_type: 'child_run',
      timestamp: '2026-03-09T10:02:00Z',
      session_id: 'child-1',
      parent_session_id: 'hb-1',
      project_id: 'agent-hub',
      agent_slug: 'git-agent',
      session_type: 'completion',
      status: 'completed',
      role: null,
      content: null,
      summary_oneliner: 'Updated files',
      display_summary: 'Updated files, reran dt -q -d, and closed task-123.',
      current_branch: 'task-branch',
      external_id: 'task-123',
      model: 'claude-sonnet',
      live_summary: null,
      live_status: null,
      message_count: 1,
      tool_count: 2,
      event_previews: [
        {
          id: 'preview-c-1',
          event_type: 'tool_result',
          created_at: '2026-03-09T10:02:10Z',
          role: null,
          tool_name: 'dt -q -d',
          content_preview: 'passed',
          tool_input_preview: null,
          tool_output_preview: '{"status":"ok"}',
          duration_ms: 1200,
          model_used: 'claude-sonnet',
        },
      ],
      ...buildPulseFields({
        issue_markers: [
          {
            event_id: 'preview-c-issue',
            event_type: 'tool_result',
            created_at: '2026-03-09T10:02:10Z',
            tool_name: 'dt -q -d',
            tags: ['tool_friction', 'retries'],
            primary_tag: 'tool_friction',
            root_causes: ['tool'],
            primary_root_cause: 'tool',
            title: 'dt -q -d hit tool friction',
            summary: longToolFrictionSummary,
            detail: `dt -q -d hit tool friction\nCommand: git status --short --branch && st context task-123 && st done task-123 --message "Verified autocode completion; quality gate passed."\nVerified autocode completion; quality gate passed.`,
            fingerprint: 'tool-friction:dt-q-d',
          },
        ],
        pulse_tags: ['friction', 'tool_friction', 'retries'],
        primary_pulse_tag: 'tool_friction',
        root_causes: ['tool'],
        primary_root_cause: 'tool',
        pulse_summary:
          'dt -q -d hit repeated tool friction; retried repeated steps',
      }),
    },
  ]
  return {
    entries,
    total: entries.length,
    page: 1,
    page_size: 100,
    matches: [
      {
        entry_id: 'h-1',
        session_id: 'hb-1',
        entry_type: 'heartbeat',
        timestamp: '2026-03-09T10:01:00Z',
        snippet: 'Checked active work',
      },
    ],
    match_count: 1,
    pulse: {
      metrics: [
        {
          key: 'friction',
          label: 'Friction',
          count: 2,
          description:
            'Sessions that showed warnings, failures, stalls, or other operational drag.',
        },
        {
          key: 'warning',
          label: 'Warnings',
          count: 1,
          description:
            'Runs that completed but still reported warnings or blockers.',
        },
        {
          key: 'tool_friction',
          label: 'Tool Friction',
          count: 1,
          description:
            'Runs where tools failed, were missing, or wasted turns before progress resumed.',
        },
        {
          key: 'recovered',
          label: 'Recovered',
          count: 1,
          description:
            'Runs that hit trouble but still recovered before finishing.',
        },
      ],
      issue_groups: [
        {
          fingerprint: 'tool-friction:dt-q-d',
          title: 'dt -q -d kept failing or wasting turns',
          summary: 'dt -q -d hit repeated tool friction',
          count: 1,
          primary_tag: 'tool_friction',
          root_cause: 'tool',
          agent_slugs: ['git-agent'],
          latest_entry_id: 'c-1',
          latest_session_id: 'child-1',
          latest_timestamp: '2026-03-09T10:02:00Z',
        },
      ],
      agent_scorecards: [
        {
          agent_slug: 'git-agent',
          label: 'git agent',
          session_count: 1,
          success_count: 1,
          friction_count: 1,
          error_count: 0,
          recovered_count: 0,
          stalled_count: 0,
          instruction_drift_count: 0,
          tool_friction_count: 1,
          median_runtime_seconds: 90,
          top_issue: 'dt -q -d kept failing or wasting turns',
          top_root_cause: 'tool',
        },
      ],
    },
  }
}

vi.mock('@/lib/api/persona-stream', () => ({
  fetchPersonaStream: (...args: unknown[]) => mockFetchPersonaStream(...args),
}))

vi.mock('@/lib/api/sessions', async () => {
  const actual =
    await vi.importActual<typeof import('@/lib/api/sessions')>(
      '@/lib/api/sessions',
    )
  return {
    ...actual,
    fetchSessionEvents: (...args: unknown[]) => mockFetchSessionEvents(...args),
  }
})

vi.mock('@/components/chat/session-dropdown', () => ({
  SessionDropdown: () => <div data-testid="session-dropdown">sessions</div>,
}))

vi.mock('@/app/persona/components/TimeRangeDropdown', () => ({
  TimeRangeDropdown: () => <div data-testid="time-range">24h</div>,
}))

vi.mock('@/hooks/use-session-events', () => ({
  useSessionEvents: () => ({
    events: [],
    status: 'connected',
    error: null,
    subscriptionId: 'sub-1',
    connect: vi.fn(),
    disconnect: vi.fn(),
    updateFilters: vi.fn(),
    clearEvents: vi.fn(),
  }),
}))

vi.mock('@/components/error/toast', () => ({
  useToastActions: () => ({
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  }),
}))

vi.mock('@agent-hub/chat-ui', () => ({
  MessageBubble: ({ message }: { message: { content: string } }) => (
    <div>{message.content}</div>
  ),
  MessageInput: () => <div data-testid="message-input">composer</div>,
  useChatStream: (...args: unknown[]) => mockUseChatStream(...args),
}))

function openHealthOverview() {
  fireEvent.click(screen.getByRole('button', { name: /Health overview/i }))
}

function getToolFrictionFilterButton() {
  const button = screen
    .getAllByRole('button', { name: /Tool Friction/i })
    .find((candidate) =>
      candidate.textContent?.includes('Runs where tools failed'),
    )
  if (!button) {
    throw new Error('Missing Tool Friction overview filter button')
  }
  return button
}

describe('UnifiedPersonaWorkspace', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseChatStream.mockReturnValue({
      messages: [],
      status: 'idle',
      error: null,
      currentSessionId: 'chat-1',
      sendMessage: vi.fn(),
      cancelStream: vi.fn(),
      resetSession: vi.fn(),
    })
    mockFetchPersonaStream.mockResolvedValue(buildStreamResponse())
    mockFetchSessionEvents.mockImplementation(async (sessionId: string) => {
      if (sessionId === 'hb-1') {
        return {
          session_id: 'hb-1',
          total: 3,
          max_turn: 1,
          events: [
            {
              id: 'evt-h-0',
              turn: 1,
              sequence: 0,
              event_type: 'system_message',
              role: 'system',
              content:
                '# PERSONA SAFETY BOUNDARIES\n<heartbeat_instructions>\nKeep every raw heartbeat detail forever.',
              tool_name: null,
              tool_input: null,
              tool_output: null,
              tokens: null,
              duration_ms: null,
              model_used: 'claude-sonnet',
              agent_id: null,
              agent_name: null,
              created_at: '2026-03-09T10:01:09Z',
            },
            {
              id: 'evt-h-1',
              turn: 1,
              sequence: 1,
              event_type: 'tool_use',
              role: null,
              content: null,
              tool_name: 'st ready-all',
              tool_input: {
                project: 'agent-hub',
                command: 'st ready-all --compact',
              },
              tool_output: null,
              tokens: null,
              duration_ms: null,
              model_used: 'claude-sonnet',
              agent_id: null,
              agent_name: null,
              created_at: '2026-03-09T10:01:10Z',
            },
            {
              id: 'evt-h-2',
              turn: 1,
              sequence: 2,
              event_type: 'tool_result',
              role: null,
              content: null,
              tool_name: 'st ready-all',
              tool_input: null,
              tool_output: { status: 'ok', content: 'Ready queue is clear' },
              tokens: null,
              duration_ms: 900,
              model_used: 'claude-sonnet',
              agent_id: null,
              agent_name: null,
              created_at: '2026-03-09T10:01:11Z',
            },
          ],
        }
      }
      if (sessionId === 'hb-2') {
        return {
          session_id: 'hb-2',
          total: 1,
          max_turn: 1,
          events: [
            {
              id: 'evt-h-3',
              turn: 1,
              sequence: 1,
              event_type: 'tool_result',
              role: null,
              content: null,
              tool_name: 'st ready-all',
              tool_input: null,
              tool_output: { status: 'ok', content: 'No additional work' },
              tokens: null,
              duration_ms: 800,
              model_used: 'claude-sonnet',
              agent_id: null,
              agent_name: null,
              created_at: '2026-03-09T10:03:10Z',
            },
          ],
        }
      }
      return {
        session_id: 'child-1',
        total: 2,
        max_turn: 1,
        events: [
          {
            id: 'evt-c-1',
            turn: 1,
            sequence: 1,
            event_type: 'tool_use',
            role: null,
            content: null,
            tool_name: 'dt -q -d',
            tool_input: { command: 'dt -q -d', project: 'agent-hub' },
            tool_output: null,
            tokens: null,
            duration_ms: null,
            model_used: 'claude-sonnet',
            agent_id: null,
            agent_name: null,
            created_at: '2026-03-09T10:02:09Z',
          },
          {
            id: 'evt-c-2',
            turn: 1,
            sequence: 2,
            event_type: 'tool_result',
            role: null,
            content: null,
            tool_name: 'dt -q -d',
            tool_input: null,
            tool_output: {
              status: 'ok',
              content: 'Checks passed',
              files_touched: ['frontend/src/app/persona/page.tsx'],
            },
            tokens: null,
            duration_ms: 1200,
            model_used: 'claude-sonnet',
            agent_id: null,
            agent_name: null,
            created_at: '2026-03-09T10:02:10Z',
          },
        ],
      }
    })
  })

  it('renders a unified stream with messages, heartbeat summaries, child runs, and composer', async () => {
    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('pause that task')).toBeInTheDocument()
    })

    const heartbeatItem = screen.getAllByTestId('stream-item')[1]
    expect(heartbeatItem).toHaveTextContent('Checked active work')
    expect(heartbeatItem).toHaveTextContent(/git-agent\s*on agent-hub/i)
    expect(screen.getByTestId('message-input')).toBeInTheDocument()

    openHealthOverview()

    expect(screen.getByText('Repeated Friction')).toBeInTheDocument()
    expect(screen.getByText('Agent Scorecards')).toBeInTheDocument()
    expect(
      screen.getByText('dt -q -d kept failing or wasting turns'),
    ).toBeInTheDocument()
    const timelineTimes = document.querySelectorAll('time[datetime]')
    expect(timelineTimes).toHaveLength(2)
  })

  it('locks chat runtime to the active session project', async () => {
    render(
      <UnifiedPersonaWorkspace
        persona={{
          id: 1,
          name: 'Avery',
          personality: null,
          user_profile: null,
          heartbeat_instructions: null,
          user_context: null,
          voice_id: 'voice',
          voice_enabled: false,
          heartbeat_interval_minutes: 30,
          execution_state: 'active',
          avatar_url: null,
          greeting: null,
          onboarding_complete: true,
          onboarding_phase: 'complete',
          onboarding_attempts: 0,
          session_reset_mode: 'off',
          session_reset_hour: 9,
          session_reset_idle_minutes: 120,
          limits: null,
          agent_slug: 'persona',
          version: 1,
          updated_at: null,
        }}
        runtime={{
          primarySession: {
            id: 'sess-1',
            project_id: 'summitflow',
            provider: 'claude',
            model: 'claude-sonnet',
            status: 'active',
            agent_slug: 'persona',
            session_type: 'completion',
            parent_session_id: null,
            external_id: null,
            current_branch: 'main',
            live_activity: {
              phase: 'waiting_for_model',
              status: 'active',
              summary: 'Working summitflow task',
              health: 'ok',
              stalled: false,
              current_tool_name: null,
              outstanding_tool_calls: 0,
              tool_calls_count: 1,
              files_touched: [],
            },
            message_count: 0,
            total_input_tokens: 400,
            total_output_tokens: 200,
            created_at: '2026-04-15T14:00:00Z',
            updated_at: '2026-04-15T14:01:00Z',
          },
          primarySessionDetails: null,
          activePersonaSessions: [{ id: 'sess-1' }] as never[],
          activeChildSessions: [] as never[],
          loading: false,
          error: null,
          stoppingSessionId: null,
          runtimeSyncKey: 'sync-1',
          refresh: vi.fn().mockResolvedValue(undefined),
          stopSession: vi.fn().mockResolvedValue(true),
          stopCurrentStream: vi.fn().mockResolvedValue(true),
          stopActiveWork: vi
            .fn()
            .mockResolvedValue({ cancelled: 1, attempted: 1 }),
        }}
        agentSlug="persona"
        activeSessionId="sess-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey="sync-1"
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(mockUseChatStream).toHaveBeenCalled()
    })

    expect(mockUseChatStream.mock.calls.at(-1)?.[0]).toMatchObject({
      sessionId: 'sess-1',
      apiConfig: {
        projectId: 'summitflow',
      },
    })
    expect(
      screen.getAllByText((content) => content.includes('summitflow')).length,
    ).toBeGreaterThan(0)
  })

  it('does not let background runtime hijack a fresh thread target', async () => {
    render(
      <UnifiedPersonaWorkspace
        persona={{
          id: 1,
          name: 'Avery',
          personality: null,
          user_profile: null,
          heartbeat_instructions: null,
          user_context: null,
          voice_id: 'voice',
          voice_enabled: false,
          heartbeat_interval_minutes: 30,
          execution_state: 'active',
          avatar_url: null,
          greeting: null,
          onboarding_complete: true,
          onboarding_phase: 'complete',
          onboarding_attempts: 0,
          session_reset_mode: 'off',
          session_reset_hour: 9,
          session_reset_idle_minutes: 120,
          limits: null,
          agent_slug: 'persona',
          version: 1,
          updated_at: null,
        }}
        runtime={{
          primarySession: {
            id: 'sess-1',
            project_id: 'summitflow',
            provider: 'claude',
            model: 'claude-sonnet',
            status: 'active',
            agent_slug: 'persona',
            session_type: 'completion',
            parent_session_id: null,
            external_id: null,
            current_branch: 'main',
            live_activity: {
              phase: 'waiting_for_model',
              status: 'active',
              summary: 'Background summitflow work still running',
              health: 'ok',
              stalled: false,
              current_tool_name: null,
              outstanding_tool_calls: 0,
              tool_calls_count: 1,
              files_touched: [],
            },
            message_count: 0,
            total_input_tokens: 400,
            total_output_tokens: 200,
            created_at: '2026-04-15T14:00:00Z',
            updated_at: '2026-04-15T14:01:00Z',
          },
          primarySessionDetails: null,
          activePersonaSessions: [{ id: 'sess-1' }] as never[],
          activeChildSessions: [] as never[],
          loading: false,
          error: null,
          stoppingSessionId: null,
          runtimeSyncKey: 'sync-1',
          refresh: vi.fn().mockResolvedValue(undefined),
          stopSession: vi.fn().mockResolvedValue(true),
          stopCurrentStream: vi.fn().mockResolvedValue(true),
          stopActiveWork: vi
            .fn()
            .mockResolvedValue({ cancelled: 1, attempted: 1 }),
        }}
        agentSlug="persona"
        activeSessionId={null}
        sidebarRefreshTrigger={0}
        runtimeSyncKey="sync-1"
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(mockUseChatStream).toHaveBeenCalled()
    })

    expect(mockUseChatStream.mock.calls.at(-1)?.[0]).toMatchObject({
      sessionId: undefined,
      apiConfig: {
        projectId: 'agent-hub',
      },
    })
    expect(
      screen.queryByText('Next thread target · summitflow'),
    ).not.toBeInTheDocument()
    expect(
      screen.getAllByText('Waiting for model response').length,
    ).toBeGreaterThan(0)
  })

  it('filters the timeline from the pulse controls', async () => {
    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('Tool Friction')).toBeInTheDocument()
    })

    openHealthOverview()
    fireEvent.click(getToolFrictionFilterButton())

    await waitFor(() => {
      expect(screen.queryByText('pause that task')).not.toBeInTheDocument()
    })

    expect(
      screen.getByRole('button', {
        name: /git-agent.*on agent-hub.*task-123/i,
      }),
    ).toBeInTheDocument()
    expect(
      screen.queryByText(
        /Checked active work across queue, cleanup, and session truth\./i,
      ),
    ).not.toBeInTheDocument()
    expect(screen.getByText('dt -q -d hit tool friction')).toBeInTheDocument()
  })

  it('dedupes duplicate warning markers on the collapsed heartbeat card', async () => {
    const response = buildStreamResponse()
    const heartbeat = response.entries.find((entry) => entry.id === 'h-1')
    if (!heartbeat) {
      throw new Error('Missing heartbeat entry')
    }
    heartbeat.issue_markers = [
      {
        event_id: 'preview-h-issue',
        event_type: 'assistant_message',
        created_at: '2026-03-09T10:01:20Z',
        tool_name: null,
        tags: ['warning'],
        primary_tag: 'warning',
        root_causes: ['context'],
        primary_root_cause: 'context',
        title: 'Completed with warnings',
        summary: `[{'type': 'text', 'text': "TASK:task-605a52fc|pending|P2|task|STANDARD\\nTITLE:Live validation: Persona dispatch judgment after workflow cleanup\\nDESCRIPTION:Temporary validation task to confirm the persona still reaches a clear readiness judgment after the latest workflow fixes.\\nOBJECTIVE:Use the persona on a temporary validation task and confirm the current task surfaces still lead to a clear dispatch judgment without extra friction."}]`,
        detail: `[{'type': 'text', 'text': "TASK:task-605a52fc|pending|P2|task|STANDARD\\nTITLE:Live validation: Persona dispatch judgment after workflow cleanup\\nDESCRIPTION:Temporary validation task to confirm the persona still reaches a clear readiness judgment after the latest workflow fixes.\\nOBJECTIVE:Use the persona on a temporary validation task and confirm the current task surfaces still lead to a clear dispatch judgment without extra friction."}]`,
        fingerprint: 'warning:task-605a52fc',
      },
      {
        event_id: 'summary-h-1',
        event_type: 'session_summary',
        created_at: '2026-03-09T10:01:25Z',
        tool_name: null,
        tags: ['warning'],
        primary_tag: 'warning',
        root_causes: ['context'],
        primary_root_cause: 'context',
        title: 'Completed with warnings',
        summary: 'Completed with warnings while reviewing task-605a52fc',
        detail: 'Completed with warnings while reviewing task-605a52fc',
        fingerprint: null,
      },
    ]
    mockFetchPersonaStream.mockResolvedValueOnce(response)

    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('Completed with warnings')).toBeInTheDocument()
    })

    expect(screen.getAllByText('Completed with warnings')).toHaveLength(1)
    expect(screen.queryByText(/\[\{'type': 'text'/)).not.toBeInTheDocument()
  })

  it('renders stream items in chronological order with newest at the bottom', async () => {
    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(screen.getAllByTestId('stream-item')).toHaveLength(3)
    })

    const timestamps = screen
      .getAllByTestId('stream-item')
      .map((item) => item.getAttribute('data-timestamp'))

    expect(timestamps).toEqual([
      '2026-03-09T10:00:00.000Z',
      '2026-03-09T10:01:00.000Z',
      '2026-03-09T10:02:00.000Z',
    ])
  })

  it('lands at the latest entry on initial load instead of jumping to the active chat session', async () => {
    const scrollToSpy = vi.fn()
    const scrollIntoViewSpy = vi.fn()

    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: scrollToSpy,
    })
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoViewSpy,
    })

    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('pause that task')).toBeInTheDocument()
    })

    await waitFor(() => {
      expect(scrollToSpy).toHaveBeenCalled()
    })

    expect(scrollIntoViewSpy).not.toHaveBeenCalled()
  })

  it('nests child runs under their parent work block', async () => {
    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(
        screen.getByRole('button', {
          name: /git-agent.*on agent-hub.*task-123/i,
        }),
      ).toBeInTheDocument()
    })

    const heartbeatItem = screen.getAllByTestId('stream-item')[1]
    expect(
      within(heartbeatItem).getByRole('button', {
        name: /git-agent.*on agent-hub.*task-123/i,
      }),
    ).toBeInTheDocument()
  })

  it('expands heartbeat and child run details inline', async () => {
    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /^Heartbeat completed/i }),
      ).toBeInTheDocument()
    })

    fireEvent.click(
      screen.getByRole('button', { name: /^Heartbeat completed/i }),
    )
    fireEvent.click(
      screen.getByRole('button', {
        name: /git-agent.*on agent-hub.*task-123/i,
      }),
    )

    await waitFor(() => {
      expect(mockFetchSessionEvents).toHaveBeenCalledWith('hb-1', {
        page: 1,
        page_size: 500,
      })
      expect(mockFetchSessionEvents).toHaveBeenCalledWith('child-1', {
        page: 1,
        page_size: 500,
      })
    })

    expect(screen.getByText('Ready queue is clear')).toBeInTheDocument()
    expect(screen.getAllByText('Checks passed').length).toBeGreaterThan(0)
    expect(
      screen.queryByText(/PERSONA SAFETY BOUNDARIES/i),
    ).not.toBeInTheDocument()
    expect(
      screen.getAllByText('Completed with warnings').length,
    ).toBeGreaterThan(0)
    expect(screen.getByText('dt -q -d hit tool friction')).toBeInTheDocument()
    expect(screen.getAllByText(/Warning/i).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/Tool Friction/i).length).toBeGreaterThan(0)
    expect(screen.queryByText(/"status"/)).not.toBeInTheDocument()
  })

  it('expands only the selected heartbeat detail block', async () => {
    mockFetchPersonaStream.mockResolvedValue(
      buildStreamResponse({ includeSecondHeartbeat: true }),
    )

    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(
        screen.getAllByRole('button', { name: /^Heartbeat completed/i }),
      ).toHaveLength(2)
    })

    fireEvent.click(
      screen.getAllByRole('button', { name: /^Heartbeat completed/i })[0],
    )

    await waitFor(() => {
      expect(mockFetchSessionEvents).toHaveBeenCalledWith('hb-1', {
        page: 1,
        page_size: 500,
      })
    })

    expect(mockFetchSessionEvents).not.toHaveBeenCalledWith('hb-2', {
      page: 1,
      page_size: 500,
    })
    expect(screen.getByText('Ready queue is clear')).toBeInTheDocument()
    expect(screen.queryByText('No additional work')).not.toBeInTheDocument()
  })

  it('shows search match chips and can jump through them', async () => {
    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('pause that task')).toBeInTheDocument()
    })

    expect(
      screen.getByText(
        /Checked active work across queue, cleanup, and session truth\./i,
      ),
    ).toBeInTheDocument()

    fireEvent.change(
      screen.getByPlaceholderText(
        /Search history, tasks, files, agents\.\.\./i,
      ),
      {
        target: { value: 'active work' },
      },
    )

    await waitFor(() => {
      expect(screen.getByText(/1 of 1 matches/)).toBeInTheDocument()
    })

    expect(
      screen.getByRole('button', { name: /Checked active work/i }),
    ).toBeInTheDocument()
    expect(mockFetchPersonaStream).toHaveBeenLastCalledWith(
      expect.objectContaining({
        search: 'active work',
      }),
    )
  })

  it('turns off auto-follow when the user scrolls up to inspect older work', async () => {
    mockFetchPersonaStream.mockResolvedValue(
      buildStreamResponse({
        heartbeatStatus: 'active',
        heartbeatLiveStatus: 'active',
      }),
    )

    const scrollToSpy = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: scrollToSpy,
    })

    const { rerender } = render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('pause that task')).toBeInTheDocument()
    })

    const container = screen.getByTestId('stream-scroll-container')
    Object.defineProperty(container, 'scrollHeight', {
      configurable: true,
      value: 1000,
    })
    Object.defineProperty(container, 'clientHeight', {
      configurable: true,
      value: 400,
    })
    Object.defineProperty(container, 'scrollTop', {
      configurable: true,
      writable: true,
      value: 600,
    })

    await waitFor(() => {
      expect(scrollToSpy).toHaveBeenCalled()
    })

    scrollToSpy.mockClear()
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 450))
      ;(container as HTMLDivElement).scrollTop = 120
      fireEvent.scroll(container)
    })

    expect(screen.getByText(/Jump to latest/)).toBeInTheDocument()

    await act(async () => {
      rerender(
        <UnifiedPersonaWorkspace
          agentSlug="persona"
          activeSessionId="chat-1"
          sidebarRefreshTrigger={1}
          runtimeSyncKey=""
          onSelectSession={vi.fn()}
          onSessionCreated={vi.fn()}
          onNewSession={vi.fn()}
        />,
      )
    })

    await waitFor(() => {
      expect(mockFetchPersonaStream).toHaveBeenCalledTimes(2)
    })

    expect(
      scrollToSpy.mock.calls.every(
        ([options]) => options?.behavior !== 'smooth',
      ),
    ).toBe(true)
  })

  it('hides jump-to-latest after the user manually scrolls back to the bottom', async () => {
    const scrollToSpy = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: scrollToSpy,
    })

    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText('pause that task')).toBeInTheDocument()
    })

    const container = screen.getByTestId('stream-scroll-container')
    Object.defineProperty(container, 'scrollHeight', {
      configurable: true,
      value: 1000,
    })
    Object.defineProperty(container, 'clientHeight', {
      configurable: true,
      value: 400,
    })
    Object.defineProperty(container, 'scrollTop', {
      configurable: true,
      writable: true,
      value: 600,
    })

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 450))
      ;(container as HTMLDivElement).scrollTop = 120
      fireEvent.scroll(container)
    })

    expect(screen.getByText(/Jump to latest/)).toBeInTheDocument()

    await act(async () => {
      ;(container as HTMLDivElement).scrollTop = 601
      fireEvent.scroll(container)
    })

    await waitFor(() => {
      expect(screen.queryByText(/Jump to latest/)).not.toBeInTheDocument()
    })
  })
})
