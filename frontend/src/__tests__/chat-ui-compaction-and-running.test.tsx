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

function fakeClient(session: Record<string, unknown>) {
  const turn = gate()
  const client = {
    turns: {
      attach: vi.fn(() => turn.events()),
      stream: vi.fn(),
      cancel: vi.fn(),
    },
    sessions: {
      get: vi.fn(async () => ({ id: 's1', project_id: 'aico', ...session })),
      fork: vi.fn(),
    },
    models: { list: vi.fn().mockResolvedValue([]) },
  } as unknown as ChatHubClient
  return { client, turn }
}

function renderPanel(client: ChatHubClient, running?: boolean) {
  return render(
    <ChatPanel
      agentSlug="chat"
      sessionId="s1"
      client={client}
      layout="transcript"
      running={running}
    />,
    { wrapper: createQueryClientWrapper() },
  )
}

const user = {
  id: 'u1',
  role: 'user',
  content: 'read the repo',
  created_at: '2026-10-29T10:00:00Z',
}

const compactionRecord = {
  status: 'ok',
  tokens_before: 9200,
  tokens_after: 6400,
  messages_summarized: 12,
  summarizer_model: 'small-model',
  cost_usd: 0.002,
}

describe('the context compacted note', () => {
  beforeEach(() => localStorage.clear())

  it('shows one quiet line where a stored chat was compacted, when it is reopened', async () => {
    const { client } = fakeClient({
      turn_state: 'idle',
      messages: [
        user,
        {
          id: 'c1',
          role: 'system',
          kind: 'compaction',
          content:
            'Context compacted: 9200 -> 6400 tokens (12 messages summarized by small-model)',
          compaction: compactionRecord,
          created_at: '2026-10-29T10:00:02Z',
        },
        {
          id: 'a1',
          role: 'assistant',
          content: 'Done.',
          created_at: '2026-10-29T10:00:05Z',
        },
      ],
    })
    renderPanel(client)

    const line = await screen.findByTestId('compaction-line')
    expect(line).toHaveTextContent('Context compacted · 9.2k → 6.4k tokens')
    expect(line).toHaveAttribute(
      'title',
      '12 earlier messages summarized by small-model $0.002',
    )
    expect(screen.getAllByTestId('compaction-line')).toHaveLength(1)
    // Between your message and the answer, not after it.
    const order = Array.from(
      screen.getByTestId('transcript').querySelectorAll('[data-testid]'),
    )
      .map((el) => el.getAttribute('data-testid'))
      .filter((id) =>
        ['user-entry', 'compaction-line', 'agent-entry'].includes(id ?? ''),
      )
    expect(order).toEqual(['user-entry', 'compaction-line', 'agent-entry'])
  })

  it('shows the line live when the event arrives, above the answer being written, and once on a replay', async () => {
    const { client, turn } = fakeClient({
      turn_state: 'running',
      turn_phase: 'thinking',
      messages: [user],
    })
    renderPanel(client)
    await screen.findByTestId('user-entry')

    await act(async () => {
      turn.push(
        { type: 'content', seq: 1, content: 'Reading. ' },
        {
          type: 'context_compacted',
          seq: 2,
          status: 'ok',
          tokens_before: 9200,
          tokens_after: 6400,
        },
        { type: 'content', seq: 3, content: 'Done.' },
      )
    })
    const line = await screen.findByTestId('compaction-line')
    expect(line).toHaveTextContent('Context compacted · 9.2k → 6.4k tokens')
    expect(await screen.findByText(/Reading\./)).toBeInTheDocument()
    const lineAt = line.compareDocumentPosition(
      screen.getByTestId('agent-entry'),
    )
    expect(lineAt & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    // The same compaction again (a replayed stream) is not a second line.
    await act(async () => {
      turn.push({
        type: 'context_compacted',
        seq: 4,
        status: 'ok',
        tokens_before: 9200,
        tokens_after: 6400,
      })
    })
    await waitFor(() =>
      expect(screen.getAllByTestId('compaction-line')).toHaveLength(1),
    )
  })

  it('says so when a compaction failed, and leaves a size out when the server gave none', async () => {
    const { client, turn } = fakeClient({
      turn_state: 'running',
      turn_phase: 'thinking',
      messages: [user],
    })
    renderPanel(client)
    await screen.findByTestId('user-entry')
    await act(async () => {
      turn.push({ type: 'context_compacted', seq: 1, status: 'ok' })
      turn.push({
        type: 'context_compacted',
        seq: 2,
        status: 'failed',
        tokens_before: 9200,
      })
    })
    await waitFor(() =>
      expect(screen.getAllByTestId('compaction-line')).toHaveLength(2),
    )
    const [first, second] = screen.getAllByTestId('compaction-line')
    expect(first).toHaveTextContent(/^Context compacted$/)
    expect(second).toHaveTextContent('Context compaction failed')
  })
})

describe('what is sent to the model', () => {
  it('leaves the compaction note out of the conversation', async () => {
    const stream = vi.fn(async function* () {
      yield { type: 'done', seq: 1, session_id: 's1' }
    })
    const client = {
      turns: { attach: vi.fn(), stream, cancel: vi.fn() },
      sessions: {
        get: vi.fn(async () => ({
          id: 's1',
          project_id: 'aico',
          turn_state: 'idle',
          messages: [
            user,
            {
              id: 'c1',
              role: 'system',
              kind: 'compaction',
              content: 'Context compacted: 1 -> 1 tokens',
              compaction: compactionRecord,
              created_at: '2026-10-29T10:00:02Z',
            },
            {
              id: 'a1',
              role: 'assistant',
              content: 'Done.',
              created_at: '2026-10-29T10:00:05Z',
            },
          ],
        })),
        fork: vi.fn(),
      },
      models: { list: vi.fn().mockResolvedValue([]) },
    } as unknown as ChatHubClient
    const { result } = renderHook(() =>
      useChatStream({ client, agentSlug: 'chat', sessionId: 's1' }),
    )
    await waitFor(() => expect(result.current.messages).toHaveLength(3))
    await act(async () => {
      result.current.sendMessage('and then?')
    })
    await waitFor(() => expect(stream).toHaveBeenCalled())
    const sent = (
      stream.mock.calls[0] as unknown as [
        { messages: { role: string; content: string }[] },
      ]
    )[0].messages
    expect(sent.map((m) => m.role)).toEqual(['user', 'assistant', 'user'])
    expect(JSON.stringify(sent)).not.toContain('compacted')
  })
})

describe('a step that has tool activity but no answer yet', () => {
  beforeEach(() => localStorage.clear())

  const standIn = {
    id: 'evt-9-synthetic-assistant',
    role: 'assistant',
    kind: 'incomplete_turn',
    content:
      'Tool activity recorded without a final assistant summary. Tools: bash.',
    created_at: '2026-10-29T10:00:05Z',
    tool_executions: [
      {
        id: 't1',
        name: 'bash',
        input: { command: 'ls' },
        status: 'complete',
        result: 'a',
      },
    ],
  }
  const session = { turn_state: 'idle', messages: [user, standIn] }

  it('says Running, not Ready, and does not show the stand-in note while the host says the step runs', async () => {
    const { client } = fakeClient(session)
    renderPanel(client, true)
    await screen.findByTestId('agent-entry')
    const pill = screen.getByTestId('activity-pill')
    expect(pill).toHaveTextContent('Running')
    expect(pill).not.toHaveTextContent('Ready')
    expect(
      screen.queryByText(/without a final assistant summary/),
    ).not.toBeInTheDocument()
    // The work done so far still shows.
    expect(screen.getByText(/bash/i)).toBeInTheDocument()
  })

  it('keeps Ready and the note for a step that is over and ended without an answer', async () => {
    const { client } = fakeClient(session)
    renderPanel(client, false)
    expect(
      await screen.findByText(/without a final assistant summary/),
    ).toBeInTheDocument()
    expect(screen.getByTestId('activity-pill')).toHaveTextContent('Ready')
  })

  it('keeps a real answer as it is while running', async () => {
    const { client } = fakeClient({
      turn_state: 'idle',
      messages: [
        user,
        {
          id: 'a1',
          role: 'assistant',
          content: 'Here is the answer.',
          created_at: '2026-10-29T10:00:05Z',
        },
      ],
    })
    renderPanel(client, true)
    expect(await screen.findByText('Here is the answer.')).toBeInTheDocument()
  })
})
