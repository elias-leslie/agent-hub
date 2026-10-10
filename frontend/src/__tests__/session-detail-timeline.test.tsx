import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { Suspense } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SessionDetailPage from '@/app/sessions/[id]/page'
import {
  fetchSession,
  fetchSessionEvents,
  fetchSessionEventsSummary,
  querySessions,
  type Session,
  type SessionListItem,
} from '@/lib/api/sessions'
import type { SessionEventsResponse, TimelineEvent } from '@/types/events'

let currentSearch = new URLSearchParams()
const replace = vi.fn()

vi.mock('next/navigation', () => ({
  usePathname: () => '/sessions/parent-session',
  useRouter: () => ({ replace }),
  useSearchParams: () => currentSearch,
}))
vi.mock('@/lib/api/sessions', async (original) => ({
  ...(await original<typeof import('@/lib/api/sessions')>()),
  fetchSession: vi.fn(),
  fetchSessionEvents: vi.fn(),
  fetchSessionEventsSummary: vi.fn(),
  querySessions: vi.fn(),
}))
vi.mock('@/lib/api/native-capture', () => ({
  fetchNativeCaptureStatus: vi.fn().mockResolvedValue(null),
}))

const PARENT_ID = '01a11233-0000-7000-8000-000000000001'
const CHILD_ID = '01a11934-0000-7000-8000-000000000002'

function session(overrides: Partial<Session> = {}): Session {
  return {
    id: PARENT_ID,
    project_id: 'agent-hub',
    provider: 'anthropic',
    model: 'claude-opus-5-5',
    status: 'completed',
    agent_slug: null,
    session_type: 'claude_code',
    created_at: '2026-10-01T10:00:00Z',
    updated_at: '2026-10-01T12:00:00Z',
    last_active_at: '2026-10-01T12:05:00Z',
    title: 'Redesign the sessions page',
    current_branch: 'main',
    child_session_count: 0,
    live_activity: {
      phase: 'completed',
      status: 'completed',
      health: 'completed',
      stalled: false,
      outstanding_tool_calls: 0,
      tool_calls_count: 3,
      files_touched: [],
    },
    ...overrides,
  }
}

function event(
  id: string,
  overrides: Partial<TimelineEvent> = {},
): TimelineEvent {
  return {
    id,
    turn: 1,
    sequence: Number(id.replace(/\D/g, '')) || 1,
    event_type: 'assistant_message',
    role: 'assistant',
    content: `Toy content ${id}`,
    tool_name: null,
    tool_input: null,
    tool_output: null,
    tokens: null,
    duration_ms: null,
    model_used: null,
    agent_id: null,
    agent_name: null,
    created_at: '2026-10-01T12:00:00Z',
    ...overrides,
  }
}

function page(
  events: TimelineEvent[],
  total: number,
  nextAfter: string | null,
): SessionEventsResponse {
  return {
    session_id: PARENT_ID,
    events,
    total,
    max_turn: 2,
    next_after: nextAfter,
  }
}

function child(id: string, overrides: Partial<SessionListItem> = {}) {
  return {
    id,
    project_id: 'agent-hub',
    provider: 'codex',
    model: 'codex/unknown',
    status: 'completed',
    agent_slug: 'worker',
    session_type: 'agent',
    message_count: 2,
    total_input_tokens: 0,
    total_output_tokens: 0,
    created_at: '2026-10-01T10:00:00Z',
    updated_at: '2026-10-01T12:00:00Z',
    last_active_at: '2026-10-01T11:00:00Z',
    ...overrides,
  } as SessionListItem
}

async function mount(id = PARENT_ID) {
  const params = Promise.resolve({ id })
  await act(async () => {
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <Suspense fallback={<p>Loading route</p>}>
          <SessionDetailPage params={params} />
        </Suspense>
      </QueryClientProvider>,
    )
  })
}

beforeEach(() => {
  currentSearch = new URLSearchParams()
  vi.mocked(fetchSession).mockResolvedValue(session())
  vi.mocked(fetchSessionEventsSummary).mockResolvedValue({
    total: 1203,
    by_type: {
      user_message: 3,
      assistant_message: 1000,
      tool_use: 100,
      child_session_update: 90,
      usage_counter: 10,
    },
    usage_known: false,
  })
})

afterEach(() => vi.clearAllMocks())

describe('session detail timeline', () => {
  it('fetches the session without events and labels the header honestly', async () => {
    vi.mocked(fetchSessionEvents).mockResolvedValue(
      page([event('e1')], 1, null),
    )
    await mount()
    expect(fetchSession).toHaveBeenCalledWith(PARENT_ID, {
      includeEvents: false,
    })
    const heading = await screen.findByRole('heading', {
      name: 'Redesign the sessions page',
    })
    expect(heading).toBeInTheDocument()
    expect(screen.getByText('coding')).toBeInTheDocument()
    expect(screen.getByText(PARENT_ID)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Copy session ID' }),
    ).toBeInTheDocument()
    // Duration covers hours, and the live label does not repeat the status.
    expect(screen.getByText('2h 5m')).toBeInTheDocument()
    expect(screen.queryByText(/completed · completed/)).not.toBeInTheDocument()
    // Only Timeline and Info tabs without children.
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Timeline',
      'Info',
    ])
  })

  it('loads windows of 500 oldest first, excluding noise, and follows next_after', async () => {
    vi.mocked(fetchSessionEvents).mockImplementation(async (_id, params) =>
      params?.after === 'cursor-2'
        ? page([event('e3')], 3, null)
        : page([event('e1'), event('e2')], 3, 'cursor-2'),
    )
    await mount()
    expect(await screen.findByText('Toy content e1')).toBeInTheDocument()
    expect(fetchSessionEvents).toHaveBeenCalledWith(PARENT_ID, {
      page_size: 500,
      exclude_types: ['child_session_update', 'usage_counter'],
      q: undefined,
      after: undefined,
    })
    const status = screen.getByText(/Showing 2 of 3 matching events/)
    expect(status).toHaveTextContent('1,203 in session')
    expect(status).toHaveTextContent('Partial view')

    fireEvent.click(screen.getByRole('button', { name: 'Load more events' }))
    expect(await screen.findByText('Toy content e3')).toBeInTheDocument()
    expect(vi.mocked(fetchSessionEvents).mock.calls.at(-1)?.[1]).toMatchObject({
      after: 'cursor-2',
      page_size: 500,
    })
    expect(
      screen.getByText(/Showing 3 of 3 matching events/),
    ).not.toHaveTextContent('Partial view')
    expect(screen.getByText('End of matching events')).toBeInTheDocument()
  })

  it('takes chip counts from the summary, not loaded events, and toggles noise back in', async () => {
    vi.mocked(fetchSessionEvents).mockResolvedValue(
      page([event('e1')], 1103, null),
    )
    await mount()
    await screen.findByText('Toy content e1')
    const assistantChip = screen.getByRole('button', { name: /Assistant/ })
    expect(assistantChip).toHaveTextContent('1000')
    expect(assistantChip).toHaveAttribute('aria-pressed', 'false')

    const noise = screen.getByRole('button', {
      name: /Show sub-agent updates and usage counters/,
    })
    expect(noise).toHaveTextContent('100')
    fireEvent.click(noise)
    await waitFor(() =>
      expect(
        vi.mocked(fetchSessionEvents).mock.calls.at(-1)?.[1],
      ).toMatchObject({ exclude_types: [] }),
    )
    expect(
      screen.getByRole('button', {
        name: /Showing sub-agent updates and usage counters/,
      }),
    ).toHaveAttribute('aria-pressed', 'true')
  })

  it('selecting a type chip filters on the server via exclude_types', async () => {
    vi.mocked(fetchSessionEvents).mockResolvedValue(
      page([event('e1')], 1103, null),
    )
    await mount()
    await screen.findByText('Toy content e1')
    fireEvent.click(screen.getByRole('button', { name: /User/ }))
    await waitFor(() => {
      const excluded = vi.mocked(fetchSessionEvents).mock.calls.at(-1)?.[1]
        ?.exclude_types as string[]
      expect(excluded).toContain('assistant_message')
      expect(excluded).toContain('child_session_update')
      expect(excluded).not.toContain('user_message')
    })
  })

  it('debounces search and sends it to the server as q', async () => {
    vi.mocked(fetchSessionEvents).mockImplementation(async (_id, params) =>
      params?.q
        ? page([event('e9', { content: 'Matched by server' })], 1, null)
        : page([event('e1')], 1103, null),
    )
    await mount()
    await screen.findByText('Toy content e1')
    fireEvent.change(
      screen.getByRole('searchbox', { name: 'Search session events' }),
      { target: { value: 'needle' } },
    )
    expect(await screen.findByText('Matched by server')).toBeInTheDocument()
    const searchCalls = vi
      .mocked(fetchSessionEvents)
      .mock.calls.filter(([, params]) => params?.q)
    expect(searchCalls).toHaveLength(1)
    expect(searchCalls[0][1]).toMatchObject({ q: 'needle' })
  })

  it('links child_session events to the child session', async () => {
    vi.mocked(fetchSessionEvents).mockResolvedValue(
      page(
        [
          event('e1', {
            event_type: 'child_session_started',
            content: `Child session ${CHILD_ID} started (worker)`,
            tool_output: { child_session_id: CHILD_ID },
          }),
        ],
        1,
        null,
      ),
    )
    await mount()
    const link = await screen.findByRole('link', {
      name: /Open sub-agent 01a11934/,
    })
    expect(link).toHaveAttribute('href', `/sessions/${CHILD_ID}`)
  })

  it('shows an honest empty state when only noise was recorded', async () => {
    vi.mocked(fetchSessionEvents).mockResolvedValue(page([], 0, null))
    await mount()
    expect(
      await screen.findByText(
        'This session only recorded sub-agent updates and usage counters',
      ),
    ).toBeInTheDocument()
  })
})

describe('session detail navigation', () => {
  it('renders a breadcrumb with the parent title linked for a sub-agent', async () => {
    vi.mocked(fetchSession).mockImplementation(async (id) =>
      id === CHILD_ID
        ? session({
            id: CHILD_ID,
            parent_session_id: PARENT_ID,
            title: null,
            summary_oneliner: 'Child worker summary',
          })
        : session(),
    )
    vi.mocked(fetchSessionEvents).mockResolvedValue(page([], 0, null))
    await mount(CHILD_ID)
    const nav = await screen.findByRole('navigation', { name: 'Breadcrumb' })
    expect(within(nav).getByRole('link', { name: /Sessions/ })).toHaveAttribute(
      'href',
      '/sessions',
    )
    const parentLink = await within(nav).findByRole('link', {
      name: 'Redesign the sessions page',
    })
    expect(parentLink).toHaveAttribute('href', `/sessions/${PARENT_ID}`)
    expect(within(nav).getByText('Child worker summary')).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(fetchSession).toHaveBeenCalledWith(PARENT_ID, {
      includeEvents: false,
    })
  })

  it('lists sub-agents with cursor paging and usage honesty', async () => {
    currentSearch = new URLSearchParams('tab=subagents')
    vi.mocked(fetchSession).mockResolvedValue(
      session({ child_session_count: 51 }),
    )
    vi.mocked(fetchSessionEvents).mockResolvedValue(page([], 0, null))
    vi.mocked(querySessions).mockImplementation(async (query) =>
      query.cursor === 'next-50'
        ? {
            sessions: [child('c-last', { title: 'Last child' })],
            total: 51,
            page: 1,
            page_size: 50,
            next_cursor: null,
          }
        : {
            sessions: [
              child('c-1', {
                title: 'First child',
                usage_known: true,
                usage_input_tokens: 1200,
                usage_output_tokens: 300,
              }),
              child('c-2', { title: 'Second child' }),
            ],
            total: 51,
            page: 1,
            page_size: 50,
            next_cursor: 'next-50',
          },
    )
    await mount()
    const panel = await screen.findByRole('tabpanel', { name: 'Sub-agents' })
    expect(await within(panel).findByText('First child')).toBeInTheDocument()
    expect(querySessions).toHaveBeenCalledWith({
      parent_session_id: PARENT_ID,
      page_size: 50,
      sort_by: 'last_active',
      sort_direction: 'desc',
      cursor: undefined,
    })
    expect(within(panel).getByText('1.2K in / 300 out')).toBeInTheDocument()
    expect(within(panel).getByText('usage not captured')).toBeInTheDocument()
    expect(
      within(panel).getByText(/Showing 2 of 51 sub-agents/),
    ).toBeInTheDocument()
    expect(
      within(panel).getByRole('link', { name: /First child/ }),
    ).toHaveAttribute('href', '/sessions/c-1')

    fireEvent.click(
      within(panel).getByRole('button', { name: 'Load more sub-agents' }),
    )
    expect(await within(panel).findByText('Last child')).toBeInTheDocument()
    expect(vi.mocked(querySessions).mock.calls.at(-1)?.[0]).toMatchObject({
      cursor: 'next-50',
    })
    expect(
      within(panel).queryByRole('button', { name: 'Load more sub-agents' }),
    ).not.toBeInTheDocument()

    const tabs = screen.getAllByRole('tab')
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'Timeline',
      'Sub-agents',
      'Info',
    ])
    fireEvent.keyDown(tabs[1], { key: 'ArrowRight' })
    expect(replace).toHaveBeenCalledWith('/sessions/parent-session?tab=info', {
      scroll: false,
    })
  })
})
