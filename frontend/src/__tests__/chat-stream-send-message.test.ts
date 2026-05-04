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
        max_turns: 80,
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
  })
})
