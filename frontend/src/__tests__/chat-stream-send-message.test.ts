import { describe, expect, it, vi } from 'vitest'

import { sendMessage } from '../../../packages/chat-ui/src/hooks/chat-stream/send-message'

const mockProcessStream = vi.fn()

vi.mock(
  '../../../packages/chat-ui/src/hooks/chat-stream/stream-processor',
  () => ({
    processStream: (...args: unknown[]) => mockProcessStream(...args),
  }),
)

describe('chat stream sendMessage', () => {
  it('requests real tool execution when tools are enabled', async () => {
    mockProcessStream.mockResolvedValue('finished')

    const client = { turns: {} } as never
    await sendMessage({
      client,
      content: 'Inspect repo and fix the issue.',
      agentSlug: 'assistant',
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
      projectId: 'summitflow',
      memoryGroupPrefix: 'agent:',
      includeRoles: ['system', 'system-extra', 'user-context'],
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

    expect(mockProcessStream).toHaveBeenCalledWith(
      client,
      expect.objectContaining({
        project_id: 'summitflow',
        tools_enabled: true,
        execute_tools: true,
        include_roles: ['system', 'system-extra', 'user-context'],
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
      expect.objectContaining({ assistantId: expect.any(String) }),
      expect.any(AbortSignal),
    )
    const request = mockProcessStream.mock.calls[0][1]
    expect(request).not.toHaveProperty('max_turns')
  })
})
