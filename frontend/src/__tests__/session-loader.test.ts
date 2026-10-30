import { describe, expect, it, vi } from 'vitest'

import { loadSession } from '../../../packages/chat-ui/src/hooks/chat-stream/session-loader'

describe('loadSession', () => {
  it('deduplicates repeated tool executions across loaded assistant messages', async () => {
    const get = vi.fn().mockResolvedValue({
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
    })

    const loaded = await loadSession(
      { sessions: { get } } as never,
      'session-1',
    )
    expect(get).toHaveBeenCalledWith('session-1', { includeMessages: true })

    expect(loaded.messages[0]?.toolExecutions).toBeUndefined()
    expect(
      loaded.messages[1]?.toolExecutions?.map((tool) => tool.name),
    ).toEqual(['bash', 'read_file'])
  })

  it('keeps repeated identical prompts and answers from different turns, in order', async () => {
    const at = (n: number) => `2026-05-01T00:0${n}:00Z`
    const messages = [1, 2].flatMap((turn) => [
      {
        id: `u${turn}`,
        role: 'user',
        content: 'How many prime numbers are below 100?',
        created_at: at(turn * 2),
      },
      {
        id: `a${turn}`,
        role: 'assistant',
        content: '25.',
        created_at: at(turn * 2 + 1),
      },
    ])
    const get = vi
      .fn()
      .mockResolvedValue({ id: 'session-1', provider: 'openai', messages })

    const loaded = await loadSession(
      { sessions: { get } } as never,
      'session-1',
    )

    expect(loaded.messages.map((m) => m.id)).toEqual([
      'loaded-u1',
      'loaded-a1',
      'loaded-u2',
      'loaded-a2',
    ])
    expect(loaded.messages.map((m) => m.role)).toEqual([
      'user',
      'assistant',
      'user',
      'assistant',
    ])
  })

  it('shows one stored message once when the read lists its id twice', async () => {
    const row = {
      id: 'u1',
      role: 'user',
      content: 'hello',
      created_at: '2026-05-01T00:00:00Z',
    }
    const get = vi.fn().mockResolvedValue({
      id: 'session-1',
      provider: 'openai',
      messages: [
        row,
        { ...row },
        {
          id: 'a1',
          role: 'assistant',
          content: 'hi',
          created_at: '2026-05-01T00:01:00Z',
        },
      ],
    })

    const loaded = await loadSession(
      { sessions: { get } } as never,
      'session-1',
    )

    expect(loaded.messages.map((m) => m.id)).toEqual(['loaded-u1', 'loaded-a1'])
  })
})
