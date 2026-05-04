import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PersonaOperatorDeck } from '@/app/persona/components/PersonaOperatorDeck'
import type { PersonaRuntimeState } from '@/app/persona/hooks/usePersonaRuntime'

const mockFetchProjectPermissions = vi.fn()
const mockFetchExecutionPermission = vi.fn()
const mockFetchPersonaPreview = vi.fn()
const mockFetchPersonaAutomations = vi.fn()
const mockRunPersonaWorkflow = vi.fn()

vi.mock('@/components/error/toast', () => ({
  useToastActions: () => ({
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  }),
}))

vi.mock('@/lib/api/project-permissions', () => ({
  fetchProjectPermissions: (...args: unknown[]) =>
    mockFetchProjectPermissions(...args),
  fetchExecutionPermission: (...args: unknown[]) =>
    mockFetchExecutionPermission(...args),
}))

vi.mock('@/lib/api/persona-operator', async () => {
  const actual = await vi.importActual<
    typeof import('@/lib/api/persona-operator')
  >('@/lib/api/persona-operator')
  return {
    ...actual,
    runPersonaWorkflow: (...args: unknown[]) => mockRunPersonaWorkflow(...args),
    fetchPersonaOperatorPreview: (...args: unknown[]) =>
      mockFetchPersonaPreview(...args),
    fetchPersonaAutomations: (...args: unknown[]) =>
      mockFetchPersonaAutomations(...args),
    createPersonaAutomation: vi.fn(),
    updatePersonaAutomation: vi.fn(),
    deletePersonaAutomation: vi.fn(),
    triggerPersonaAutomation: vi.fn(),
  }
})

const basePersona = {
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
} as const

function buildRuntime(overrides: Partial<PersonaRuntimeState> = {}) {
  return {
    primarySession: {
      id: 'sess-root',
      project_id: 'agent-hub',
      provider: 'claude',
      model: 'claude-sonnet',
      status: 'active',
      agent_slug: 'persona',
      session_type: 'completion',
      parent_session_id: null,
      external_id: null,
      current_branch: 'main',
      live_activity: {
        phase: 'running_tool',
        status: 'active',
        summary: 'Running verification',
        health: 'ok',
        stalled: false,
        current_tool_name: 'bash',
        outstanding_tool_calls: 1,
        tool_calls_count: 3,
        files_touched: ['frontend/src/app/persona/page.tsx'],
      },
      message_count: 0,
      total_input_tokens: 1200,
      total_output_tokens: 400,
      created_at: '2026-04-15T14:00:00Z',
      updated_at: '2026-04-15T14:01:00Z',
    },
    primarySessionDetails: {
      id: 'sess-root',
      project_id: 'agent-hub',
      provider: 'claude',
      model: 'claude-sonnet',
      status: 'active',
      agent_slug: 'persona',
      session_type: 'completion',
      created_at: '2026-04-15T14:00:00Z',
      updated_at: '2026-04-15T14:01:00Z',
      context_usage: {
        used_tokens: 3200,
        limit_tokens: 8000,
        percent_used: 40,
        remaining_tokens: 4800,
        warning: null,
      },
      total_input_tokens: 1200,
      total_output_tokens: 400,
    },
    activePersonaSessions: [{ id: 'sess-root' }],
    activeChildSessions: [],
    loading: false,
    error: null,
    stoppingSessionId: null,
    runtimeSyncKey: 'sync-1',
    refresh: vi.fn().mockResolvedValue(undefined),
    stopSession: vi.fn().mockResolvedValue(true),
    stopCurrentStream: vi.fn().mockResolvedValue(true),
    stopActiveWork: vi.fn().mockResolvedValue({ cancelled: 1, attempted: 1 }),
    ...overrides,
  } as unknown as PersonaRuntimeState
}

function renderDeck(
  overrides?: Partial<ComponentProps<typeof PersonaOperatorDeck>>,
) {
  const runtimeOverrides = overrides?.runtime
    ? (overrides.runtime as unknown as Partial<PersonaRuntimeState>)
    : undefined
  const runtime = buildRuntime(runtimeOverrides)
  return render(
    <PersonaOperatorDeck
      persona={basePersona as never}
      personaName="Avery"
      runtime={runtime}
      focusSession={
        (overrides?.focusSession as never) ?? runtime.primarySession
      }
      focusSessionDetails={
        (overrides?.focusSessionDetails as never) ??
        runtime.primarySessionDetails
      }
      entries={overrides?.entries ?? []}
      pulse={
        (overrides?.pulse as never) ?? {
          metrics: [],
          issue_groups: [],
          agent_scorecards: [],
        }
      }
      visiblePulseMetrics={overrides?.visiblePulseMetrics ?? []}
      activeSessionId={
        overrides?.activeSessionId ?? runtime.primarySession?.id ?? null
      }
      selectedProjectId={overrides?.selectedProjectId ?? 'agent-hub'}
      onProjectChange={overrides?.onProjectChange ?? vi.fn()}
      onSelectSession={overrides?.onSelectSession ?? vi.fn()}
      sendMessage={overrides?.sendMessage ?? vi.fn()}
      applyPulseFilter={overrides?.applyPulseFilter ?? vi.fn()}
      inspectAgentPulse={overrides?.inspectAgentPulse ?? vi.fn()}
      activeTab={overrides?.activeTab ?? 'workflow'}
      onTabChange={overrides?.onTabChange ?? vi.fn()}
    />,
  )
}

describe('PersonaOperatorDeck', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockFetchProjectPermissions.mockResolvedValue([
      {
        project_id: 'agent-hub',
        permission_tier: 'write',
        auto_exec_enabled: false,
        execution_start_hour: 0,
        execution_end_hour: 24,
        root_path: '/srv/workspaces/projects/agent-hub',
        updated_at: '2026-04-15T12:00:00Z',
        created_at: '2026-04-01T12:00:00Z',
      },
    ])
    mockFetchExecutionPermission.mockResolvedValue({
      allowed: true,
      permission_tier: 'write',
      auto_exec_enabled: false,
      in_time_window: true,
      reason: 'allowed',
    })
    mockFetchPersonaPreview.mockResolvedValue({
      slug: 'persona',
      name: 'Avery',
      combined_prompt: 'system',
      full_context: 'system',
      memory_query: 'status',
      memory_debug: { total_tokens: 2400 },
      loaded_memory_uuids: [],
      reference_uuids: [],
      mandate_count: 1,
      guardrail_count: 1,
      mandate_uuids: ['aaaa1111'],
      guardrail_uuids: ['bbbb2222'],
      task_type: 'chat',
      phase: null,
      project_id: 'agent-hub',
      task_prompt: 'status',
      sections: [],
    })
    mockFetchPersonaAutomations.mockResolvedValue([
      {
        id: 'job-1',
        name: 'Daily operator check',
        schedule_type: 'every',
        schedule_value: '3600000',
        schedule_timezone: 'UTC',
        payload_type: 'agent_turn',
        payload_message: 'Check blockers and report back.',
        payload_title: null,
        delivery: 'none',
        enabled: true,
        last_run_at: null,
        next_run_at: '2026-04-15T15:00:00Z',
        run_count: 2,
        max_runs: null,
        created_at: '2026-04-15T12:00:00Z',
      },
    ])
    mockRunPersonaWorkflow.mockResolvedValue({
      status: 'completed',
      stages: [],
      final_output: 'done',
      total_input_tokens: 10,
      total_output_tokens: 5,
    })
  })

  it('renders lane drafts through a single draft surface', async () => {
    const sendMessage = vi.fn()

    renderDeck({
      activeTab: 'lanes',
      sendMessage,
      entries: [
        {
          id: 'child-1',
          entry_type: 'child_run',
          timestamp: '2026-04-15T14:02:00Z',
          session_id: 'child-1',
          parent_session_id: 'sess-root',
          project_id: 'agent-hub',
          agent_slug: 'coder',
          session_type: 'completion',
          status: 'active',
          role: null,
          content: null,
          summary_oneliner: 'Investigating UI state',
          display_summary: 'Investigating UI state in background lane.',
          current_branch: 'task-branch',
          external_id: null,
          model: 'claude-sonnet',
          live_summary: 'Investigating UI state',
          live_status: 'active',
          live_topic: null,
          message_count: 0,
          tool_count: 1,
          event_previews: [],
          issue_markers: [],
          pulse_tags: [],
          primary_pulse_tag: null,
          root_causes: [],
          primary_root_cause: null,
          pulse_summary: null,
        },
      ] as never,
    })

    await waitFor(() => {
      expect(screen.getByText(/Running verification/i)).toBeInTheDocument()
    })
    expect(
      screen.getByText('Investigating UI state in background lane.'),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /^Draft$/i }))
    fireEvent.change(screen.getByRole('combobox'), {
      target: { value: 'handoff' },
    })
    fireEvent.change(screen.getByLabelText(/Lane draft/i), {
      target: { value: 'Advisory handoff for lane child-1.' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Send draft/i }))

    expect(sendMessage).toHaveBeenCalledWith(
      'Advisory handoff for lane child-1.',
      undefined,
      'child-1',
    )
  })

  it('shows runtime-only child lanes even before feed entries exist', async () => {
    renderDeck({
      activeTab: 'lanes',
      runtime: buildRuntime({
        activeChildSessions: [
          {
            id: 'child-2',
            project_id: 'agent-hub',
            provider: 'codex',
            model: 'codex/gpt-5.4',
            status: 'active',
            agent_slug: 'planner',
            session_type: 'completion',
            parent_session_id: 'sess-root',
            external_id: null,
            current_branch: null,
            live_activity: {
              phase: 'waiting_for_model',
              status: 'active',
              summary: 'Planning workflow from runtime state',
              health: 'ok',
              stalled: false,
              outstanding_tool_calls: 0,
              tool_calls_count: 1,
              files_touched: [],
            },
            message_count: 1,
            total_input_tokens: 0,
            total_output_tokens: 0,
            created_at: '2026-04-15T14:03:00Z',
            updated_at: '2026-04-15T14:03:30Z',
          },
        ],
      }) as never,
      focusSession: null,
      focusSessionDetails: null,
      activeSessionId: null,
      entries: [],
    })

    await waitFor(() => {
      expect(
        screen.getByText('Planning workflow from runtime state'),
      ).toBeInTheDocument()
    })
    expect(screen.getByText(/Lanes · 1\/1/i)).toBeInTheDocument()
  })

  it('stops the focused live thread from the compact run hud', async () => {
    const stopSession = vi.fn().mockResolvedValue(true)

    renderDeck({
      runtime: buildRuntime({
        primarySession: null,
        primarySessionDetails: null,
        stopSession,
      }) as never,
      focusSession: {
        id: 'chat-live-1',
        project_id: 'agent-hub',
        provider: 'openai',
        model: 'gpt-5',
        status: 'active',
        agent_slug: 'persona',
        session_type: 'chat',
        parent_session_id: null,
        external_id: null,
        current_branch: null,
        live_activity: {
          phase: 'waiting_for_model',
          status: 'active',
          summary: 'Avery is responding',
          health: 'ok',
          stalled: false,
          current_tool_name: null,
          outstanding_tool_calls: 0,
          tool_calls_count: 0,
          files_touched: [],
        },
        message_count: 2,
        total_input_tokens: 0,
        total_output_tokens: 0,
        created_at: '2026-04-15T14:10:00Z',
        updated_at: '2026-04-15T14:10:01Z',
      } as never,
      focusSessionDetails: null,
      activeSessionId: 'chat-live-1',
    })

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /stop active work/i }),
      ).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /stop active work/i }))
    expect(stopSession).toHaveBeenCalledWith('chat-live-1')
  })

  it('threads workflow runs under the current persona root session', async () => {
    renderDeck({ activeTab: 'workflow' })

    fireEvent.change(
      screen.getByPlaceholderText(
        /Describe work\. Name the success bar and risk\./i,
      ),
      {
        target: { value: 'Audit the operator workflow flow.' },
      },
    )
    fireEvent.click(screen.getByRole('button', { name: /Run workflow/i }))

    await waitFor(() => {
      expect(mockRunPersonaWorkflow).toHaveBeenCalled()
    })

    const request = mockRunPersonaWorkflow.mock.calls[0][0]
    expect(request.parent_session_id).toBe('sess-root')
    expect(request.project_id).toBe('agent-hub')
  })
})
