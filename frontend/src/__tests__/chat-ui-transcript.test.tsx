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
import { thoughtLabel } from '../../../packages/chat-ui/src/components/ThinkingBlock'
import {
  sessionCost,
  statusLineFields,
} from '../../../packages/chat-ui/src/components/transcript/status-line'
import { interleave } from '../../../packages/chat-ui/src/components/transcript/TranscriptMessage'
import {
  describeTool,
  diffForTool,
  diffLines,
} from '../../../packages/chat-ui/src/components/transcript/tool-format'
import { createQueryClientWrapper } from './test-utils'

const at = new Date('2026-10-29T10:00:00Z')

describe('transcript tool lines', () => {
  it.each([
    [
      'read_file',
      { path: 'src/pricing/total.py', offset: 29, limit: 31 },
      'Read',
      'src/pricing/total.py · lines 30–60',
    ],
    ['read', { file_path: 'a.py' }, 'Read', 'a.py'],
    [
      'edit_file',
      { path: 'src/a.py', old_text: 'x', new_text: 'y' },
      'Edit',
      'src/a.py',
    ],
    [
      'write_file',
      { path: 'tests/t.py', content: 'a\nb\nc\n' },
      'Write',
      'tests/t.py · 3 lines',
    ],
    ['bash', { command: 'pytest -q' }, 'Bash', 'pytest -q'],
    [
      'grep',
      { pattern: 'free_shipping', path: 'src/' },
      'Search',
      '"free_shipping" in src/',
    ],
    ['search_web', { query: 'pnpm pack' }, 'Search', '"pnpm pack"'],
    [
      'fetch_web_page',
      { url: 'https://example.com/a' },
      'Fetch',
      'https://example.com/a',
    ],
    ['mcp__tether__lookup', { id: 'abc' }, 'lookup', 'abc'],
    ['custom_tool', {}, 'custom_tool', ''],
  ])('names %s as %s', (name, input, label, summary) => {
    const described = describeTool({ name, input })
    expect(described.name).toBe(label)
    expect(described.summary).toBe(summary)
  })

  it('falls back to the raw name and compact arguments for an unknown tool', () => {
    expect(
      describeTool({ name: 'weird', input: { depth: 3, deep: true } }),
    ).toMatchObject({
      kind: 'other',
      name: 'weird',
      summary: '{"depth":3,"deep":true}',
    })
  })

  it('cuts a long command to one line', () => {
    const { summary } = describeTool({
      name: 'bash',
      input: { command: `echo ${'x'.repeat(300)}\nnext` },
    })
    expect(summary.length).toBeLessThanOrEqual(120)
    expect(summary).not.toContain('\n')
  })
})

describe('transcript diffs', () => {
  it('diffs old and new text with counts', () => {
    const diff = diffForTool({
      name: 'edit_file',
      input: {
        path: 'src/pricing/total.py',
        old_text:
          'def order_total(order):\n    subtotal = a\n    return max(subtotal, 0)',
        new_text:
          'def order_total(order):\n    items = b\n    ship = c\n    return items + ship',
      },
    })
    expect(diff).not.toBeNull()
    expect(diff?.file).toBe('src/pricing/total.py')
    expect(diff?.added).toBe(3)
    expect(diff?.removed).toBe(2)
    expect(diff?.lines[0]).toEqual({
      kind: 'context',
      text: 'def order_total(order):',
    })
  })

  it('handles several edits in one call and other key spellings', () => {
    const diff = diffForTool({
      name: 'edit_file',
      input: {
        path: 'a.py',
        edits: [
          { old_text: 'one', new_text: 'uno' },
          { oldText: 'two', newText: 'dos\ntres' },
        ],
      },
    })
    expect(diff?.added).toBe(3)
    expect(diff?.removed).toBe(2)
    expect(
      diffForTool({
        name: 'str_replace',
        input: { path: 'b', old_string: 'x', new_string: 'y' },
      })?.added,
    ).toBe(1)
  })

  it('shows a written file as all additions', () => {
    const diff = diffForTool({
      name: 'write_file',
      input: { path: 't.py', content: 'a\nb\n' },
    })
    expect(diff).toMatchObject({ file: 't.py', added: 2, removed: 0 })
    expect(diff?.lines.every((line) => line.kind === 'add')).toBe(true)
  })

  it('has no diff for other tools or for arguments without text to compare', () => {
    expect(diffForTool({ name: 'bash', input: { command: 'ls' } })).toBeNull()
    expect(diffForTool({ name: 'edit_file', input: { path: 'a' } })).toBeNull()
  })

  it('keeps unchanged lines as context and finds moved lines', () => {
    expect(diffLines('a\nb\nc', 'a\nc')).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'del', text: 'b' },
      { kind: 'context', text: 'c' },
    ])
    expect(diffLines('', 'x')).toEqual([{ kind: 'add', text: 'x' }])
  })
})

describe('the thought label', () => {
  it('names a duration only when it is a second or more', () => {
    expect(thoughtLabel(8200, undefined)).toBe('Thought for 8s')
    expect(thoughtLabel(700, 1200)).toBe('Thought (1,200 tokens)')
    expect(thoughtLabel(undefined, undefined)).toBe('Thought')
  })
})

describe('the status line', () => {
  it('leaves out every field the data does not have, and never shows 0 for unknown', () => {
    expect(statusLineFields({})).toEqual({})
    expect(
      statusLineFields({
        inputTokens: 0,
        outputTokens: 0,
        costUsd: 0,
        contextPercent: null,
        branch: '',
      }),
    ).toEqual({})
    expect(
      statusLineFields({
        inputTokens: 18_230,
        outputTokens: 1_100,
        costUsd: 0.002,
        contextPercent: 23,
        branch: 'fix/x',
      }),
    ).toEqual({
      inputTokens: '18k',
      outputTokens: '1.1k',
      cost: '$0.002',
      contextPercent: 23,
      branch: 'fix/x',
    })
  })

  it('shows a used context below one percent as under one, not as zero', () => {
    expect(statusLineFields({ contextPercent: 0.4 })).toEqual({
      contextPercent: 0,
      contextUnderOne: true,
    })
    expect(statusLineFields({ contextPercent: 0 })).toEqual({
      contextPercent: 0,
    })
  })

  it('says answering while a turn runs and answered after', () => {
    const base = { requestedModel: 'a', servedModel: 'b' }
    expect(statusLineFields({ ...base, busy: true }).answerLabel).toBe(
      'answering',
    )
    expect(statusLineFields({ ...base, busy: false }).answerLabel).toBe(
      'answered',
    )
    expect(statusLineFields({ requestedModel: 'a' })).toEqual({
      requested: 'a',
    })
  })

  it('sums the session cost only when every answer reported one', () => {
    const answer = (costUsd?: number) =>
      ({
        id: String(Math.random()),
        role: 'assistant',
        content: '',
        timestamp: at,
        costUsd,
      }) as never
    expect(sessionCost([answer(0.001), answer(0.002)])).toBeCloseTo(0.003)
    expect(sessionCost([answer(0.001), answer(undefined)])).toBeUndefined()
    expect(sessionCost([])).toBeUndefined()
  })
})

describe('transcript order', () => {
  const tool = (id: string, contentOffset?: number) =>
    ({
      id,
      name: 'read_file',
      input: {},
      status: 'complete',
      startedAt: at,
      contentOffset,
    }) as never

  it('puts a call where it happened in the text', () => {
    const parts = interleave('First. Second.', [tool('a', 6)])
    expect(parts).toHaveLength(3)
    expect(parts[0]).toEqual({ text: 'First.' })
    expect('tools' in parts[1]).toBe(true)
    expect(parts[2]).toEqual({ text: ' Second.' })
  })

  it('puts the calls before the text when the answer was reloaded without offsets', () => {
    const parts = interleave('Done.', [tool('a'), tool('b')])
    expect('tools' in parts[0] && parts[0].tools).toHaveLength(2)
    expect(parts[1]).toEqual({ text: 'Done.' })
  })
})

type Event = Record<string, unknown>

function gate() {
  const queue: Event[] = []
  let wake: (() => void) | null = null
  return {
    push(...events: Event[]) {
      queue.push(...events)
      wake?.()
    },
    async *events(): AsyncGenerator<Event> {
      for (;;) {
        while (queue.length) yield queue.shift() as Event
        await new Promise<void>((resolve) => {
          wake = resolve
        })
      }
    },
  }
}

function client(session: Record<string, unknown>, queued: string[] = []) {
  const turn = gate()
  const fake = {
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
    followUps: { send: vi.fn(), pending: vi.fn(async () => queued) },
  } as unknown as ChatHubClient
  return { fake, turn }
}

function panel(fake: ChatHubClient) {
  return render(
    <ChatPanel
      agentSlug="coder"
      sessionId="s1"
      client={fake}
      layout="transcript"
    />,
    { wrapper: createQueryClientWrapper() },
  )
}

const finished = {
  turn_state: 'idle',
  requested_model: 'deepseek-v4.1-flash',
  current_branch: 'fix/order-total',
  total_input_tokens: 18_230,
  total_output_tokens: 1_100,
  context_usage: {
    used_tokens: 23_000,
    limit_tokens: 100_000,
    percent_used: 23,
    measured: true,
  },
  messages: [
    {
      id: 'u1',
      role: 'user',
      content: 'Fix the total.',
      created_at: '2026-10-29T10:00:00Z',
    },
    {
      id: 'a1',
      role: 'assistant',
      content: 'Fixed.',
      created_at: '2026-10-29T10:00:05Z',
      model_used: 'deepseek-v4.1-flash',
      thinking: 'Look at the file first.',
      thinking_tokens: 12,
      tool_executions: [
        {
          id: 't1',
          name: 'read_file',
          input: { path: 'total.py' },
          status: 'complete',
          result: 'def f(): pass',
        },
        {
          id: 't2',
          name: 'edit_file',
          input: { path: 'total.py', old_text: 'pass', new_text: 'return 1' },
          status: 'complete',
          result: 'edited',
        },
        {
          id: 't3',
          name: 'bash',
          input: { command: 'false' },
          status: 'error',
          result: 'exit 1',
        },
      ],
    },
  ],
}

describe('the transcript layout', () => {
  beforeEach(() => localStorage.clear())

  it('shows your message with an edge, the agent as plain prose, and tool calls as lines', async () => {
    const { fake } = client(finished)
    panel(fake)
    expect(await screen.findByText('Fixed.')).toBeInTheDocument()
    expect(
      within(screen.getByTestId('user-entry')).getByText('You'),
    ).toBeInTheDocument()
    // No tool box, no "Tool executions" heading.
    expect(screen.queryByText(/Tool executions/)).not.toBeInTheDocument()
    const lines = screen.getAllByTestId('tool-line')
    expect(lines.map((line) => line.getAttribute('data-kind'))).toEqual([
      'read',
      'edit',
      'bash',
    ])
    expect(lines[0]).toHaveTextContent('Read')
    expect(lines[0]).toHaveTextContent('total.py')
    expect(lines.map((line) => line.getAttribute('data-status'))).toEqual([
      'complete',
      'complete',
      'error',
    ])
  })

  it('opens an edit with its diff, folds the rest, and opens output on click', async () => {
    const { fake } = client(finished)
    panel(fake)
    await screen.findByText('Fixed.')
    const [read, edit, bash] = screen.getAllByTestId('tool-line')
    expect(within(edit).getByTestId('tool-diff')).toBeInTheDocument()
    expect(within(edit).getByTestId('diff-file')).toHaveTextContent('total.py')
    expect(within(edit).getByTestId('diff-counts')).toHaveTextContent('+1')
    expect(within(edit).getByTestId('diff-counts')).toHaveTextContent('−1')
    // A call that failed says why; a finished read stays folded until clicked.
    expect(within(bash).getByTestId('tool-output')).toHaveTextContent('exit 1')
    expect(within(read).queryByTestId('tool-output')).not.toBeInTheDocument()
    fireEvent.click(within(read).getByRole('button'))
    expect(within(read).getByTestId('tool-output')).toHaveTextContent(
      'def f(): pass',
    )
  })

  it('folds thinking as "Thought" and opens it on click', async () => {
    const { fake } = client(finished)
    panel(fake)
    const toggle = await screen.findByTestId('thinking-toggle')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(toggle).toHaveTextContent('Thought (12 tokens)')
    expect(screen.queryByTestId('thinking-body')).not.toBeInTheDocument()
    fireEvent.click(toggle)
    expect(screen.getByTestId('thinking-body')).toHaveTextContent(
      'Look at the file first.',
    )
  })

  it('reads the status line from the session, leaving out what it does not have', async () => {
    const { fake } = client(finished)
    const view = panel(fake)
    await screen.findByText('Fixed.')
    const line = screen.getByTestId('status-line')
    expect(line).toHaveTextContent('requested deepseek-v4.1-flash')
    expect(line).toHaveTextContent('answered deepseek-v4.1-flash')
    expect(line).toHaveTextContent('in 18k')
    expect(line).toHaveTextContent('out 1.1k')
    expect(line).toHaveTextContent('23%')
    expect(line).toHaveTextContent('fix/order-total')
    // Reopened answers did not report a cost, so the line has none.
    expect(screen.queryByTestId('status-cost')).not.toBeInTheDocument()
    view.unmount()

    const bare = client({
      ...finished,
      current_branch: null,
      total_input_tokens: 0,
      total_output_tokens: 0,
      context_usage: null,
    })
    panel(bare.fake)
    await screen.findByText('Fixed.')
    const bareLine = screen.getByTestId('status-line')
    expect(bareLine).not.toHaveTextContent(/\bin \d/)
    expect(bareLine).not.toHaveTextContent('context')
    expect(screen.queryByTestId('status-branch')).not.toBeInTheDocument()
    expect(bareLine).not.toHaveTextContent('0')
  })

  it('shows a running turn: dot pulses, Bash counts seconds, Send reads Queue, queued follow-ups are chips', async () => {
    const { fake, turn } = client(
      {
        turn_state: 'running',
        turn_phase: 'waiting_for_model',
        messages: finished.messages.slice(0, 1),
      },
      ['Also update the changelog'],
    )
    panel(fake)
    await screen.findByText('Fix the total.')
    await act(async () => {
      turn.push({
        type: 'tool_use',
        seq: 1,
        tool_id: 'b1',
        tool_name: 'bash',
        tool_input: { command: 'pytest -q' },
      })
    })
    const line = await screen.findByTestId('tool-line')
    expect(line).toHaveAttribute('data-status', 'running')
    expect(within(line).getByTestId('tool-dot').className).toContain(
      'animate-pulse',
    )
    expect(within(line).getByTestId('tool-dot').className).toContain(
      'motion-reduce:animate-none',
    )
    expect(within(line).getByTestId('tool-output')).toHaveTextContent(
      /running… \d+s/,
    )
    await waitFor(() =>
      expect(screen.getByTestId('activity-pill')).toHaveTextContent(
        'Running Bash',
      ),
    )
    expect(screen.getByTestId('send-button')).toHaveTextContent('Queue')
    expect(screen.getByTestId('stop-button')).toBeInTheDocument()
    const chip = await screen.findByTestId('queued-message')
    expect(chip).toHaveTextContent('Also update the changelog')
    // The queue cannot drop a message, so the chip has no remove button.
    expect(within(chip).queryByRole('button')).not.toBeInTheDocument()
  })

  it('keeps thinking open while it is the live phase, then folds it with the time it took', async () => {
    const { fake, turn } = client({
      turn_state: 'running',
      turn_phase: 'waiting_for_model',
      messages: finished.messages.slice(0, 1),
    })
    panel(fake)
    await screen.findByText('Fix the total.')
    await act(async () => {
      turn.push({ type: 'thinking', seq: 1, content: 'hmm' })
    })
    const toggle = await screen.findByTestId('thinking-toggle')
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(toggle).toHaveTextContent('Thinking')
    await act(async () => {
      turn.push({ type: 'content', seq: 2, content: 'Answer.' })
    })
    await waitFor(() =>
      expect(screen.getByTestId('thinking-toggle')).toHaveAttribute(
        'aria-expanded',
        'false',
      ),
    )
  })
})
