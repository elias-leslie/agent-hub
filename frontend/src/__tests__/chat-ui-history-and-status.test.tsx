import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChatHubClient } from '../../../packages/chat-ui/src/client'
import { ChatPanel } from '../../../packages/chat-ui/src/components/chat-panel'
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

// A finished turn as GET /api/sessions/{id} returns it: the answer carries the turn's thinking and tool calls.
const finishedTurn = {
  turn_state: 'idle',
  messages: [
    {
      id: 'u1',
      role: 'user',
      content: 'what version is the sdk?',
      created_at: '2026-10-28T10:00:00Z',
    },
    {
      id: 'a1',
      role: 'assistant',
      content: 'The SDK is 0.1.2.',
      created_at: '2026-10-28T10:00:05Z',
      thinking: 'I should read the SDK package file.',
      thinking_tokens: 17,
      tool_executions: [
        {
          id: 't1',
          name: 'read',
          input: { path: 'packages/agent-hub-sdk/package.json' },
          status: 'complete',
          result: '{"version": "0.1.2"}',
        },
        {
          id: 't2',
          name: 'bash',
          input: { command: 'false' },
          status: 'error',
          result: 'exit 1',
        },
      ],
    },
  ],
}

function renderPanel(client: ChatHubClient, layout?: 'compact') {
  return render(
    <ChatPanel
      agentSlug="chat"
      sessionId="s1"
      client={client}
      layout={layout}
    />,
    { wrapper: createQueryClientWrapper() },
  )
}

describe('reopening a finished chat', () => {
  beforeEach(() => localStorage.clear())

  it("shows the turn's tool calls and thinking, folded, like the live turn did", async () => {
    const { client } = fakeClient(finishedTurn)
    renderPanel(client)

    expect(await screen.findByText('The SDK is 0.1.2.')).toBeInTheDocument()
    const tools = screen
      .getByText('Tool executions')
      .closest('div.mb-3') as HTMLElement
    expect(within(tools).getByText('(2)')).toBeInTheDocument()
    expect(within(tools).getByText('needs review')).toBeInTheDocument()
    // Folded: neither the tool rows nor the thinking text are open.
    expect(screen.queryByText('read')).not.toBeInTheDocument()
    expect(screen.queryByTestId('thinking-body')).not.toBeInTheDocument()
    const thinking = screen.getByTestId('thinking-toggle')
    expect(thinking).toHaveAttribute('aria-expanded', 'false')
    expect(thinking).toHaveTextContent('17 tokens')

    fireEvent.click(within(tools).getByRole('button', { name: /show/i }))
    expect(screen.getByText('read')).toBeInTheDocument()
    expect(screen.getByText('bash')).toBeInTheDocument()
    fireEvent.click(thinking)
    expect(screen.getByTestId('thinking-body')).toHaveTextContent(
      'I should read the SDK package file.',
    )
  })

  it('shows them again after a reload (a second panel on the same session)', async () => {
    const { client } = fakeClient(finishedTurn)
    const first = renderPanel(client)
    await screen.findByText('Tool executions')
    first.unmount()

    renderPanel(client)
    expect(await screen.findByText('Tool executions')).toBeInTheDocument()
    expect(screen.getByTestId('thinking-toggle')).toBeInTheDocument()
  })

  it('lets a host theme the thinking colour with one custom property, with the violet as the default', async () => {
    const { client } = fakeClient(finishedTurn)
    renderPanel(client)
    const toggle = await screen.findByTestId('thinking-toggle')
    expect(toggle.getAttribute('style')).toContain(
      'var(--chat-ui-thinking, oklch(71.4% 0.203 305.504))',
    )
  })
})

describe('the status pill', () => {
  beforeEach(() => localStorage.clear())

  async function pillFor(phase: string, layout?: 'compact') {
    const { client, turn } = fakeClient({
      turn_state: 'running',
      turn_phase: phase,
      messages: finishedTurn.messages.slice(0, 1),
    })
    renderPanel(client, layout)
    const pill = await screen.findByTestId('activity-pill')
    return { pill, turn }
  }

  it.each([
    ['waiting_for_model', 'waiting', 'Waiting for the model...'],
    ['thinking', 'thinking', 'Thinking...'],
    ['running_tool:read', 'calling_tool', 'Calling read...'],
    ['responding', 'streaming', 'Responding...'],
    ['retrying', 'retrying', 'Retrying...'],
  ])('names the phase %s, in both layouts, and never contradicts it', async (phase, state, label) => {
    for (const layout of [undefined, 'compact'] as const) {
      const { pill } = await pillFor(phase, layout)
      await waitFor(() => expect(pill).toHaveAttribute('data-state', state))
      expect(pill).toHaveTextContent(label)
      // The phase text is kept for screen readers only, and the pill is hidden from them to avoid a double read.
      const phaseText = screen.getByTestId('turn-phase')
      expect(phaseText).toHaveClass('sr-only')
      expect(pill).toHaveAttribute('aria-hidden', 'true')
      expect(screen.queryAllByText(/Responding/)).toHaveLength(
        phase === 'responding' ? 2 : 0,
      )
      document.body.innerHTML = ''
    }
  })

  it('follows the phase as the turn moves on', async () => {
    const { pill, turn } = await pillFor('waiting_for_model', 'compact')
    expect(pill).toHaveTextContent('Waiting for the model...')
    await act(async () => {
      turn.push({ type: 'thinking', seq: 1, content: 'hmm' })
    })
    await waitFor(() => expect(pill).toHaveTextContent('Thinking...'))
    await act(async () => {
      turn.push({
        type: 'tool_use',
        seq: 2,
        tool_id: 't1',
        tool_name: 'read',
        tool_input: {},
      })
    })
    await waitFor(() => expect(pill).toHaveTextContent('Calling read...'))
    await act(async () => {
      turn.push({ type: 'content', seq: 3, content: 'done' })
    })
    await waitFor(() => expect(pill).toHaveTextContent('Responding...'))
  })
})
