import { describe, expect, it, vi } from 'vitest'

import { loadSession } from '../../../packages/chat-ui/src/hooks/chat-stream/session-loader'

describe('loadSession', () => {
  it('deduplicates repeated tool executions across loaded assistant messages', async () => {
    const fetchFn = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'session-1',
        project_id: 'agent-hub',
        provider: 'openai',
        messages: [
          {
            id: 1,
            role: 'assistant',
            content: 'First assistant update',
            created_at: '2026-05-01T00:00:00Z',
            tool_executions: [
              {
                id: 'tool-1',
                name: 'bash',
                input: { command: 'pwd' },
                status: 'complete',
              },
              {
                id: 'tool-2',
                name: 'read_file',
                input: { path: 'README.md' },
                status: 'complete',
              },
            ],
          },
          {
            id: 2,
            role: 'assistant',
            content: 'Final assistant update',
            created_at: '2026-05-01T00:01:00Z',
            tool_executions: [
              {
                id: 'tool-1',
                name: 'bash',
                input: { command: 'pwd' },
                status: 'complete',
              },
              {
                id: 'tool-2',
                name: 'read_file',
                input: { path: 'README.md' },
                status: 'complete',
              },
            ],
          },
        ],
      }),
    })

    const loaded = await loadSession('session-1', fetchFn, '/api/sessions')

    expect(loaded.messages[0]?.toolExecutions).toBeUndefined()
    expect(
      loaded.messages[1]?.toolExecutions?.map((tool) => tool.name),
    ).toEqual(['bash', 'read_file'])
  })
})
