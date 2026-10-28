import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChatHubClient } from '../../../packages/chat-ui/src/client'
import { ChatPanel } from '../../../packages/chat-ui/src/components/chat-panel'
import { useChatStream } from '../../../packages/chat-ui/src/hooks/use-chat-stream'
import { createQueryClientWrapper } from './test-utils'

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

const history = [
  {
    id: 'm1',
    role: 'user',
    content: 'first question',
    created_at: '2026-10-28T10:00:00Z',
  },
]

/** A session whose host queues follow-ups. `world` is what the host reports; tests change it. */
function hostClient(withFollowUps = true) {
  const world = {
    turnState: 'running' as 'running' | 'idle',
    messages: history as Record<string, unknown>[],
    pending: [] as string[],
  }
  const turns: ReturnType<typeof gate>[] = []
  const attach = vi.fn((_id: string, _options?: unknown) => {
    const turn = gate()
    turns.push(turn)
    return turn.events()
  })
  const stream = vi.fn((_request: unknown, _options?: unknown) => {
    const turn = gate()
    turn.push({ type: 'done', seq: 1, session_id: 's1' })
    turn.end()
    return turn.events()
  })
  const cancel = vi
    .fn()
    .mockResolvedValue({ cancelled: true, session_id: 's1' })
  const send = vi.fn(async (_id: string, text: string) => {
    world.pending.push(text)
    return { queued: true }
  })
  const pending = vi.fn(async () => [...world.pending])
  const get = vi.fn(async () => ({
    id: 's1',
    project_id: 'aico',
    turn_state: world.turnState,
    messages: world.messages,
  }))
  const client = {
    turns: { attach, stream, cancel },
    sessions: { get, fork: vi.fn() },
    models: { list: vi.fn().mockResolvedValue([]) },
    ...(withFollowUps ? { followUps: { send, pending } } : {}),
  } as unknown as ChatHubClient
  return { client, world, turns, attach, stream, cancel, send, pending }
}

describe('chat-ui follow-ups', () => {
  beforeEach(() => localStorage.clear())

  it('queues a message sent during a turn, without cancelling or dropping the stream', async () => {
    const host = hostClient()
    const { result } = renderHook(() =>
      useChatStream({
        client: host.client,
        agentSlug: 'chat',
        sessionId: 's1',
      }),
    )
    await waitFor(() => expect(result.current.status).toBe('streaming'))
    const signal = (host.attach.mock.calls[0][1] as { signal: AbortSignal })
      .signal

    await act(async () => {
      result.current.sendMessage('and then this')
    })

    await waitFor(() =>
      expect(result.current.queued).toEqual(['and then this']),
    )
    expect(host.send).toHaveBeenCalledWith('s1', 'and then this')
    expect(host.cancel).not.toHaveBeenCalled()
    expect(host.stream).not.toHaveBeenCalled()
    expect(signal.aborted).toBe(false)
    expect(result.current.status).toBe('streaming')
  })

  it('follows the next turn when the host sends the queued message', async () => {
    const host = hostClient()
    const { result } = renderHook(() =>
      useChatStream({
        client: host.client,
        agentSlug: 'chat',
        sessionId: 's1',
      }),
    )
    await waitFor(() => expect(result.current.status).toBe('streaming'))
    await act(async () => {
      result.current.sendMessage('and then this')
    })
    await waitFor(() => expect(result.current.queued).toHaveLength(1))

    // The first turn ends; the host has not started the next one yet.
    host.world.turnState = 'idle'
    await act(async () => {
      host.turns[0].push({ type: 'done', seq: 1, session_id: 's1' })
      host.turns[0].end()
    })
    await waitFor(() => expect(result.current.status).toBe('idle'))
    expect(result.current.queued).toEqual(['and then this'])

    // The host sends it: the queue empties and the turn runs, with its prompt already stored.
    host.world.pending = []
    host.world.turnState = 'running'
    host.world.messages = [
      ...history,
      {
        id: 'm2',
        role: 'assistant',
        content: 'done',
        created_at: '2026-10-28T10:00:05Z',
      },
      {
        id: 'm3',
        role: 'user',
        content: 'and then this',
        created_at: '2026-10-28T10:00:06Z',
      },
    ]
    await waitFor(() => expect(host.attach).toHaveBeenCalledTimes(2), {
      timeout: 4000,
    })
    await waitFor(() => expect(result.current.status).toBe('streaming'))
    expect(result.current.queued).toEqual([])
    expect(result.current.messages.map((m) => m.content)).toContain(
      'and then this',
    )
  })

  it('keeps the shown queue when asking the host fails', async () => {
    const host = hostClient()
    host.world.pending = ['waiting']
    const { result } = renderHook(() =>
      useChatStream({
        client: host.client,
        agentSlug: 'chat',
        sessionId: 's1',
      }),
    )
    await waitFor(() => expect(result.current.queued).toEqual(['waiting']))
    host.pending.mockRejectedValue(new Error('host down'))
    await act(async () => {
      result.current.sendMessage('more')
    })
    await waitFor(() => expect(host.send).toHaveBeenCalled())
    expect(result.current.queued).toEqual(['waiting'])
    expect(result.current.error).toBeNull()
  })

  it('without followUps a message sent during a turn still interrupts it', async () => {
    const host = hostClient(false)
    const { result } = renderHook(() =>
      useChatStream({
        client: host.client,
        agentSlug: 'chat',
        sessionId: 's1',
      }),
    )
    await waitFor(() => expect(result.current.status).toBe('streaming'))

    await act(async () => {
      result.current.sendMessage('interrupt')
    })
    await waitFor(() => expect(host.cancel).toHaveBeenCalledWith('s1'))
    await act(async () => {
      host.turns[0].push({
        type: 'cancel_acknowledged',
        seq: 1,
        session_id: 's1',
      })
      host.turns[0].end()
    })
    await waitFor(() => expect(host.stream).toHaveBeenCalledTimes(1))
    expect(result.current.queued).toEqual([])
  })

  it('shows queued messages in a compact panel, with the input open and Stop beside Send', async () => {
    const host = hostClient()
    host.world.pending = ['waiting for you']
    render(
      <ChatPanel
        agentSlug="chat"
        sessionId="s1"
        client={host.client}
        layout="compact"
        allowModelMentions={false}
      />,
      { wrapper: createQueryClientWrapper() },
    )

    const bubble = await screen.findByTestId('queued-message')
    expect(bubble).toHaveTextContent('Queued')
    expect(bubble).toHaveTextContent('waiting for you')
    await waitFor(() =>
      expect(screen.getByTestId('stop-button')).toBeInTheDocument(),
    )
    expect(screen.getByTestId('send-button')).toBeInTheDocument()
    expect(screen.getByTestId('chat-input')).toBeEnabled()
    expect(screen.queryByRole('heading')).not.toBeInTheDocument()
    expect(screen.queryByTitle('Fork session')).not.toBeInTheDocument()
    expect(screen.queryByTestId('model-trigger')).not.toBeInTheDocument()
  })
})
