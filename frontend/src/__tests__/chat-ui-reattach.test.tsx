import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChatHubClient } from '../../../packages/chat-ui/src/client'
import { useChatStream } from '../../../packages/chat-ui/src/hooks/use-chat-stream'

type Event = Record<string, unknown>

/** A turn whose events the test releases one by one. */
function gate() {
  const queue: Event[] = []
  let wake: (() => void) | null = null
  let ended = false
  return {
    push(...events: Event[]) {
      queue.push(...events)
      wake?.()
    },
    end() {
      ended = true
      wake?.()
    },
    async *events(): AsyncGenerator<Event> {
      for (;;) {
        while (queue.length) yield queue.shift() as Event
        if (ended) return
        await new Promise<void>((resolve) => {
          wake = resolve
        })
      }
    },
  }
}

function fakeClient(session: Record<string, unknown>, turn = gate()) {
  const attach = vi.fn((_id: string, _options?: unknown) => turn.events())
  const stream = vi.fn()
  const cancel = vi
    .fn()
    .mockResolvedValue({ cancelled: true, session_id: 's1' })
  const get = vi.fn().mockResolvedValue(session)
  const client = {
    turns: { attach, stream, cancel },
    sessions: { get, fork: vi.fn() },
    models: { list: vi.fn().mockResolvedValue([]) },
  } as unknown as ChatHubClient
  return { client, attach, stream, cancel, get, turn }
}

const history = [
  {
    id: 'm1',
    role: 'user',
    content: 'earlier question',
    created_at: '2026-10-28T10:00:00Z',
  },
  {
    id: 'm2',
    role: 'assistant',
    content: 'earlier answer',
    created_at: '2026-10-28T10:00:05Z',
  },
]

describe('useChatStream reattach', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => localStorage.clear())

  it('rejoins a turn that is running when the session is opened, and shows its phase', async () => {
    const { client, attach, stream, turn } = fakeClient({
      id: 's1',
      project_id: 'agent-hub',
      turn_state: 'running',
      turn_phase: 'thinking',
      messages: history,
    })

    const { result } = renderHook(() =>
      useChatStream({ client, agentSlug: 'chat', sessionId: 's1' }),
    )

    await waitFor(() => expect(attach).toHaveBeenCalledTimes(1))
    expect(attach.mock.calls[0][0]).toBe('s1')
    expect(stream).not.toHaveBeenCalled()
    expect(result.current.status).toBe('streaming')
    expect(result.current.turnPhase).toBe('thinking')
    // History first, then the in-flight answer.
    expect(result.current.messages.map((m) => m.role)).toEqual([
      'user',
      'assistant',
      'assistant',
    ])

    await act(async () => {
      turn.push(
        { type: 'content', seq: 1, content: 'Still ' },
        { type: 'content', seq: 2, content: 'going' },
      )
    })
    await waitFor(() =>
      expect(result.current.messages.at(-1)?.content).toBe('Still going'),
    )
    expect(result.current.turnPhase).toBe('responding')

    await act(async () => {
      turn.push({ type: 'done', seq: 3, session_id: 's1' })
      turn.end()
    })
    await waitFor(() => expect(result.current.status).toBe('idle'))
    expect(result.current.turnPhase).toBeNull()
    expect(result.current.messages.at(-1)?.content).toBe('Still going')
  })

  it('shows the prompt that started the running turn, which the server stored when the turn began', async () => {
    const { client } = fakeClient({
      id: 's1',
      project_id: 'agent-hub',
      turn_state: 'running',
      messages: [
        ...history,
        {
          id: 'm3',
          role: 'user',
          content: 'the question in flight',
          created_at: '2026-10-28T10:01:00Z',
        },
      ],
    })

    const { result } = renderHook(() =>
      useChatStream({ client, agentSlug: 'chat', sessionId: 's1' }),
    )

    await waitFor(() => expect(result.current.status).toBe('streaming'))
    expect(result.current.messages.map((m) => m.content)).toEqual([
      'earlier question',
      'earlier answer',
      'the question in flight',
      '',
    ])
  })

  it('does not attach when no turn is running', async () => {
    const { client, attach } = fakeClient({
      id: 's1',
      project_id: 'agent-hub',
      turn_state: 'idle',
      messages: history,
    })

    const { result } = renderHook(() =>
      useChatStream({ client, agentSlug: 'chat', sessionId: 's1' }),
    )

    await waitFor(() => expect(result.current.status).toBe('idle'))
    expect(attach).not.toHaveBeenCalled()
    expect(result.current.messages).toHaveLength(2)
    expect(result.current.turnPhase).toBeNull()
  })

  it('reloads the session when the turn ended between the read and the attach', async () => {
    const { client, get, turn } = fakeClient({
      id: 's1',
      project_id: 'agent-hub',
      turn_state: 'running',
      messages: history,
    })
    get.mockResolvedValueOnce({
      id: 's1',
      project_id: 'agent-hub',
      turn_state: 'running',
      messages: history,
    })
    get.mockResolvedValueOnce({
      id: 's1',
      project_id: 'agent-hub',
      turn_state: 'idle',
      messages: [
        ...history,
        {
          id: 'm3',
          role: 'assistant',
          content: 'finished while away',
          created_at: '2026-10-28T10:01:00Z',
        },
      ],
    })

    const { result } = renderHook(() =>
      useChatStream({ client, agentSlug: 'chat', sessionId: 's1' }),
    )
    await waitFor(() => expect(result.current.status).toBe('streaming'))

    await act(async () => {
      turn.push({ type: 'idle', session_id: 's1', last_state: 'completed' })
      turn.end()
    })

    await waitFor(() => expect(result.current.status).toBe('idle'))
    expect(result.current.messages.at(-1)?.content).toBe('finished while away')
  })

  it('cancel asks the server to stop the turn and waits for it to end', async () => {
    const { client, cancel, turn } = fakeClient({
      id: 's1',
      project_id: 'agent-hub',
      turn_state: 'running',
      messages: history,
    })
    const { result } = renderHook(() =>
      useChatStream({ client, agentSlug: 'chat', sessionId: 's1' }),
    )
    await waitFor(() => expect(result.current.status).toBe('streaming'))

    act(() => result.current.cancelStream())
    expect(result.current.status).toBe('cancelling')
    await waitFor(() => expect(cancel).toHaveBeenCalledWith('s1'))

    await act(async () => {
      turn.push({ type: 'cancel_acknowledged', seq: 1, session_id: 's1' })
      turn.end()
    })
    await waitFor(() => expect(result.current.status).toBe('idle'))
    expect(result.current.messages.at(-1)?.cancelled).toBe(true)
  })

  it('drops its connection, not the turn, when the page goes away', async () => {
    const { client, cancel, attach } = fakeClient({
      id: 's1',
      project_id: 'agent-hub',
      turn_state: 'running',
      messages: history,
    })
    const { unmount } = renderHook(() =>
      useChatStream({ client, agentSlug: 'chat', sessionId: 's1' }),
    )
    await waitFor(() => expect(attach).toHaveBeenCalled())
    const signal = (attach.mock.calls[0][1] as { signal: AbortSignal }).signal

    unmount()

    expect(signal.aborted).toBe(true)
    expect(cancel).not.toHaveBeenCalled()
  })
})
