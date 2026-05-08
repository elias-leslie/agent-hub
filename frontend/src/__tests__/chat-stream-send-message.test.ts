import { describe, expect, it, vi } from 'vitest'

import { sendMessage } from '../../../packages/chat-ui/src/hooks/chat-stream/send-message'

const mockProcessStreamWithReconnect = vi.fn()

vi.mock(
  '../../../packages/chat-ui/src/hooks/chat-stream/stream-processor',
  () => ({
    processStreamWithReconnect: (...args: unknown[]) =>
      mockProcessStreamWithReconnect(...args),
  }),
)

describe('chat stream sendMessage', () => {
  it('requests real tool execution when tools are enabled', async () => {
    mockProcessStreamWithReconnect.mockResolvedValue(undefined)

    await sendMessage({
      content: 'Inspect repo and fix the issue.',
      agentSlug: 'persona',
      messages: [],
      temperature: 0.2,
      toolsEnabled: true,
      setMessages: vi.fn(),
      setStatus: vi.fn(),
      setError: vi.fn(),
      setCurrentSessionId: vi.fn(),
      streamStatesRef: {
        current: new Map([
          ['assistant-1', { content: '', thinking: '', tools: [], lastSeq: 0 }],
        ]),
      },
      abortControllersRef: { current: [] },
      fetchHeaders: {},
      completeEndpoint: '/api/complete',
      preferencesEndpoint: '/api/preferences',
      projectId: 'summitflow',
      memoryGroupPrefix: 'agent:',
      includeRoles: ['system', 'persona-personality', 'persona-user-context'],
      promptMode: 'chat',
      externalId: 'task-123',
      parentSessionId: 'parent-session',
      sourceMetadata: {
        transport: 'web',
        surface: 'work_chats',
        pane_id: 'pane-1',
        source_client: 'agent-hub/work-chats',
      },
      workContext: {
        mode: 'project_task',
        project_id: 'summitflow',
        task_id: 'task-123',
        pane_id: 'pane-1',
        surface: 'work_chats',
      },
    })

    expect(mockProcessStreamWithReconnect).toHaveBeenCalledWith(
      'persona',
      expect.any(String),
      expect.any(AbortController),
      expect.objectContaining({
        project_id: 'summitflow',
        tools_enabled: true,
        execute_tools: true,
        include_roles: [
          'system',
          'persona-personality',
          'persona-user-context',
        ],
        prompt_mode: 'chat',
        external_id: 'task-123',
        parent_session_id: 'parent-session',
        source_metadata: {
          transport: 'web',
          surface: 'work_chats',
          pane_id: 'pane-1',
          source_client: 'agent-hub/work-chats',
        },
        work_context: {
          mode: 'project_task',
          project_id: 'summitflow',
          task_id: 'task-123',
          pane_id: 'pane-1',
          surface: 'work_chats',
        },
      }),
      expect.any(Object),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Object),
      '/api/complete',
    )
    const request = mockProcessStreamWithReconnect.mock.calls[0][3]
    expect(request).not.toHaveProperty('max_turns')
  })

  it('sends adhoc WorkSpec runs without registered agent slug or memory', async () => {
    mockProcessStreamWithReconnect.mockClear()
    mockProcessStreamWithReconnect.mockResolvedValue(undefined)

    await sendMessage({
      content: 'Inspect current state and report exact next edit.',
      agentSlug: 'persona',
      adhoc: true,
      adhocSpec: {
        title: 'Routing smoke',
        routing_judgment: {
          workload_profile: 'coding_impl',
          risk_tier: 'normal',
          capabilities: { coding: 0.9, tool_use: 0.7, reasoning: 0.6 },
          constraints: { tool_use: false },
        },
      },
      routingExcludeProviders: ['codex', 'openai'],
      routingCostPreference: 'low_cost',
      messages: [],
      temperature: 0.2,
      toolsEnabled: true,
      setMessages: vi.fn(),
      setStatus: vi.fn(),
      setError: vi.fn(),
      setCurrentSessionId: vi.fn(),
      streamStatesRef: {
        current: new Map([
          ['assistant-1', { content: '', thinking: '', tools: [], lastSeq: 0 }],
        ]),
      },
      abortControllersRef: { current: [] },
      fetchHeaders: {},
      completeEndpoint: '/api/complete',
      preferencesEndpoint: '/api/preferences',
      projectId: 'summitflow',
      memoryGroupPrefix: 'agent:',
    })

    expect(mockProcessStreamWithReconnect).toHaveBeenCalledWith(
      'adhoc',
      expect.any(String),
      expect.any(AbortController),
      expect.objectContaining({
        adhoc: true,
        agent_slug: undefined,
        use_memory: false,
        routing_exclude_providers: ['codex', 'openai'],
        routing_cost_preference: 'low_cost',
        adhoc_spec: expect.objectContaining({
          title: 'Routing smoke',
          prompt: 'Inspect current state and report exact next edit.',
          routing_judgment: expect.objectContaining({
            workload_profile: 'coding_impl',
          }),
        }),
      }),
      expect.any(Object),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Object),
      '/api/complete',
    )
  })
})
