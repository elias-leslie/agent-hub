import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { PersonaWorkflowComposer } from '@/app/persona/components/PersonaWorkflowComposer'

const mockRunPersonaWorkflow = vi.fn()

vi.mock('@/lib/api/persona-operator', async () => {
  const actual = await vi.importActual<
    typeof import('@/lib/api/persona-operator')
  >('@/lib/api/persona-operator')
  return {
    ...actual,
    runPersonaWorkflow: (...args: unknown[]) => mockRunPersonaWorkflow(...args),
  }
})

describe('PersonaWorkflowComposer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockRunPersonaWorkflow
      .mockResolvedValueOnce({
        status: 'completed',
        final_output: 'qa output',
        total_input_tokens: 100,
        total_output_tokens: 40,
        stages: [
          {
            stage: 'clarify',
            agent_used: 'chat',
            content: 'clarify output',
            model: 'codex/gpt-5.4',
            provider: 'codex',
            session_id: 'sess-clarify',
            usage: { input_tokens: 10, output_tokens: 5, total_tokens: 15 },
            context_usage: null,
            output_usage: null,
            finish_reason: 'stop',
            memory_facts_injected: 0,
            fallback_used: false,
            fallback_reason: null,
            cited_uuids: [],
          },
          {
            stage: 'plan',
            agent_used: 'planner',
            content: 'plan output',
            model: 'codex/gpt-5.4',
            provider: 'codex',
            session_id: 'sess-plan',
            usage: { input_tokens: 20, output_tokens: 8, total_tokens: 28 },
            context_usage: null,
            output_usage: null,
            finish_reason: 'stop',
            memory_facts_injected: 0,
            fallback_used: false,
            fallback_reason: null,
            cited_uuids: [],
          },
          {
            stage: 'execute',
            agent_used: 'coder',
            content: 'execute output',
            model: 'codex/gpt-5.4',
            provider: 'codex',
            session_id: 'sess-execute',
            usage: { input_tokens: 30, output_tokens: 12, total_tokens: 42 },
            context_usage: null,
            output_usage: null,
            finish_reason: 'stop',
            memory_facts_injected: 0,
            fallback_used: false,
            fallback_reason: null,
            cited_uuids: [],
          },
        ],
      })
      .mockResolvedValueOnce({
        status: 'completed',
        final_output: 'clarify rerun',
        total_input_tokens: 12,
        total_output_tokens: 6,
        stages: [
          {
            stage: 'clarify',
            agent_used: 'chat',
            content: 'clarify rerun output',
            model: 'codex/gpt-5.4',
            provider: 'codex',
            session_id: 'sess-clarify-2',
            usage: { input_tokens: 12, output_tokens: 6, total_tokens: 18 },
            context_usage: null,
            output_usage: null,
            finish_reason: 'stop',
            memory_facts_injected: 0,
            fallback_used: false,
            fallback_reason: null,
            cited_uuids: [],
          },
        ],
      })
      .mockResolvedValueOnce({
        status: 'completed',
        final_output: 'execute rerun',
        total_input_tokens: 18,
        total_output_tokens: 9,
        stages: [
          {
            stage: 'execute',
            agent_used: 'coder',
            content: 'execute rerun output',
            model: 'codex/gpt-5.4',
            provider: 'codex',
            session_id: 'sess-execute-2',
            usage: { input_tokens: 18, output_tokens: 9, total_tokens: 27 },
            context_usage: null,
            output_usage: null,
            finish_reason: 'stop',
            memory_facts_injected: 0,
            fallback_used: false,
            fallback_reason: null,
            cited_uuids: [],
          },
        ],
      })
  })

  it('keeps workflow output compact and marks later stages stale after an earlier rerun', async () => {
    render(
      <PersonaWorkflowComposer
        projectOptions={[
          {
            id: 'agent-hub',
            name: 'agent-hub',
            rootPath: '/srv/workspaces/projects/agent-hub',
          },
        ]}
        selectedProjectId="agent-hub"
        parentSessionId="persona-root"
        onProjectChange={vi.fn()}
        onPromptChange={vi.fn()}
      />,
    )

    expect(screen.getByText(/Root persona-root/i)).toBeInTheDocument()

    fireEvent.change(
      screen.getByPlaceholderText(
        /Describe work\. Name the success bar and risk\./i,
      ),
      {
        target: { value: 'Tighten persona operator truthfulness.' },
      },
    )
    fireEvent.click(screen.getByRole('button', { name: /Run workflow/i }))

    await screen.findByText('clarify output')
    expect(screen.getByText(/chat · sess-clarify/i)).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: /^Rerun$/i })[0])
    await screen.findByText('clarify rerun output')

    expect(screen.getAllByText(/stale after clarify/i).length).toBeGreaterThan(
      0,
    )

    fireEvent.click(screen.getAllByRole('button', { name: /^Rerun$/i })[2])
    const thirdCallRequest = mockRunPersonaWorkflow.mock.calls[2][0]
    expect(thirdCallRequest.plan).toBeTruthy()
    expect(thirdCallRequest.execute).toBeTruthy()
    expect(thirdCallRequest.review).toBeUndefined()
    expect(thirdCallRequest.shared_context).toContain(
      'CLARIFY OUTPUT:\nclarify rerun output',
    )

    await screen.findByText('execute rerun output')
  })

  it('labels unlinked stage results as advisory', async () => {
    mockRunPersonaWorkflow.mockReset()
    mockRunPersonaWorkflow.mockResolvedValue({
      status: 'completed',
      final_output: 'advisory only',
      total_input_tokens: 12,
      total_output_tokens: 6,
      stages: [
        {
          stage: 'clarify',
          agent_used: 'chat',
          content: 'clarify advisory output',
          model: 'codex/gpt-5.4',
          provider: 'codex',
          session_id: null,
          usage: { input_tokens: 12, output_tokens: 6, total_tokens: 18 },
          context_usage: null,
          output_usage: null,
          finish_reason: 'stop',
          memory_facts_injected: 0,
          fallback_used: false,
          fallback_reason: null,
          cited_uuids: [],
        },
      ],
    })

    render(
      <PersonaWorkflowComposer
        projectOptions={[
          {
            id: 'agent-hub',
            name: 'agent-hub',
            rootPath: '/srv/workspaces/projects/agent-hub',
          },
        ]}
        selectedProjectId="agent-hub"
        parentSessionId="persona-root"
        onProjectChange={vi.fn()}
        onPromptChange={vi.fn()}
      />,
    )

    fireEvent.change(
      screen.getByPlaceholderText(
        /Describe work\. Name the success bar and risk\./i,
      ),
      {
        target: { value: 'Prove advisory workflow linkage stays truthful.' },
      },
    )
    fireEvent.click(screen.getByRole('button', { name: /Run workflow/i }))

    await screen.findByText('clarify advisory output')

    expect(screen.getByText(/chat · advisory/i)).toBeInTheDocument()
  })
})
