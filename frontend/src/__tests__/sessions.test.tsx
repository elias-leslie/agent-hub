import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  parseSessionListState,
  serializeSessionListState,
} from '@/app/sessions/hooks/useSessionListState'
import SessionsPage from '@/app/sessions/page'
import { DEFAULT_LIST_STATE } from '@/app/sessions/types'
import {
  formatDurationMs,
  getExecutionIdentity,
  getSessionTitle,
  getUsageSummary,
} from '@/app/sessions/utils'
import type { SessionListItem } from '@/lib/api/sessions'
import { createQueryClientWrapper } from './test-utils'

const nav = vi.hoisted(() => {
  let search = ''
  const listeners = new Set<() => void>()
  const set = (href: string) => {
    search = href.includes('?') ? href.slice(href.indexOf('?') + 1) : ''
    for (const listener of listeners) listener()
  }
  return {
    get search() {
      return search
    },
    reset(value = '') {
      search = value
    },
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    push: vi.fn((href: string) => set(href)),
    replace: vi.fn((href: string) => set(href)),
  }
})

vi.mock('next/navigation', async () => {
  const { useSyncExternalStore } = await import('react')
  return {
    usePathname: () => '/sessions',
    useRouter: () => ({ push: nav.push, replace: nav.replace }),
    useSearchParams: () => {
      const search = useSyncExternalStore(
        nav.subscribe,
        () => nav.search,
        () => nav.search,
      )
      return new URLSearchParams(search)
    },
  }
})

vi.mock('@/lib/api/sessions', async (original) => ({
  ...(await original<typeof import('@/lib/api/sessions')>()),
  querySessions: vi.fn(),
  fetchSessionFacets: vi.fn(),
  fetchSession: vi.fn(),
  fetchSessionEvents: vi.fn(),
}))

import {
  fetchSession,
  fetchSessionEvents,
  fetchSessionFacets,
  querySessions,
} from '@/lib/api/sessions'

function row(overrides: Partial<SessionListItem>): SessionListItem {
  return {
    id: 'aaaaaaaa-0000-0000-0000-000000000000',
    project_id: 'agent-hub',
    provider: 'codex',
    model: 'codex/gpt-5.5',
    status: 'completed',
    agent_slug: 'coder',
    session_type: 'agent',
    message_count: 4,
    total_input_tokens: 0,
    total_output_tokens: 0,
    child_session_count: 0,
    active_child_session_count: 0,
    usage_known: false,
    created_at: '2026-10-10T08:00:00Z',
    updated_at: '2026-10-10T09:00:00Z',
    last_active_at: '2026-10-10T10:30:00Z',
    ...overrides,
  }
}

const codexRow = row({
  id: 'c0dec0de-1111-2222-3333-444444444444',
  title: 'Fix the dispatcher retry loop',
  requested_model: 'codex/gpt-5.5',
  effective_model: 'codex/unknown',
  usage_known: true,
  usage_input_tokens: 120_000,
  usage_output_tokens: 4_500,
  usage_cached_input_tokens: 90_000,
  child_session_count: 3,
})
const claudeRow = row({
  id: 'c1a0de00-5555-6666-7777-888888888888',
  provider: 'claude',
  model: 'claude-opus-5-5',
  session_type: 'claude_code',
  title: null,
  summary_oneliner: null,
  current_branch: 'feature/sessions',
})

function listResponse(sessions: SessionListItem[], next: string | null = null) {
  return {
    sessions,
    total: sessions.length + (next ? 100 : 0),
    page: 1,
    page_size: 100,
    next_cursor: next,
  }
}

const facets = {
  status: { active: 1, completed: 40, failed: 2, running: 1 },
  kind: { coding: 30, chat: 13, completion: 900, image: 2 },
  projects: [{ project_id: 'agent-hub', count: 43 }],
}

function mount() {
  const Wrapper = createQueryClientWrapper()
  return render(
    <Wrapper>
      <SessionsPage />
    </Wrapper>,
  )
}

beforeEach(() => {
  nav.reset()
  nav.push.mockClear()
  nav.replace.mockClear()
  vi.mocked(querySessions).mockResolvedValue(
    listResponse([codexRow, claudeRow]),
  )
  vi.mocked(fetchSessionFacets).mockResolvedValue(facets)
  vi.mocked(fetchSession).mockResolvedValue({
    ...codexRow,
    message_count: 4,
    event_count: 9,
  })
  vi.mocked(fetchSessionEvents).mockResolvedValue({
    session_id: codexRow.id,
    events: [],
    total: 0,
  } as never)
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('SessionsPage', () => {
  it('keeps the accounting scope for server sorting, paging and navigation', async () => {
    nav.reset(
      'kind=all&subagents=1&benchmarks=1&accounting_start=2026-10-21T12:00:00Z&accounting_end=2026-10-22T12:00:00Z&work_role=implementation&harness=pi&sort=admin_share',
    )
    const context = {
      admin_tokens_estimate: 0,
      other_tokens_estimate: 10,
      unknown_tokens_estimate: 0,
      denominator_tokens_estimate: 10,
      argument_tokens_estimate: 10,
      returned_tokens_estimate: 0,
      admin_share: 0,
      other_share: 1,
      unknown_share: 0,
      tools_sampled: 1,
      tools_missing_output: 0,
      tokenized_argument_calls: 1,
      estimated_argument_calls: 0,
      events_truncated: false,
      input_token_encoding: 'fixture',
      output_characters_per_token: 4,
    }
    const split = {
      context_split: context,
      admin_seconds: 0,
      other_seconds: 10,
      denominator_seconds: 10,
      admin_share: 0,
      other_share: 1,
      unknown_seconds: 0,
      unknown_share: 0,
      tools_sampled: 1,
      tools_missing_duration: 0,
      duration_coverage: 1,
      events_truncated: false,
    }
    vi.mocked(querySessions)
      .mockResolvedValueOnce(
        listResponse(
          [
            { ...codexRow, activity_accounting: split },
            {
              ...claudeRow,
              activity_accounting: {
                ...split,
                context_split: {
                  ...context,
                  admin_tokens_estimate: 10,
                  other_tokens_estimate: 0,
                  admin_share: 1,
                  other_share: 0,
                },
                admin_seconds: 10,
                other_seconds: 0,
                admin_share: 1,
                other_share: 0,
              },
            },
          ],
          'server-cursor',
        ),
      )
      .mockResolvedValueOnce(listResponse([]))
    mount()
    await screen.findByText('Fix the dispatcher retry loop')
    const rows = screen.getAllByTestId('session-row')
    // The server order is authoritative, even when this page's shares increase.
    expect(rows[0]).toHaveTextContent('Admin 0.0% · Other 100.0%')
    expect(rows[1]).toHaveTextContent('Admin 100.0% · Other 0.0%')
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
    await waitFor(() =>
      expect(querySessions).toHaveBeenCalledWith(
        expect.objectContaining({
          cursor: 'server-cursor',
          accounting_start: '2026-10-21T12:00:00Z',
          accounting_end: '2026-10-22T12:00:00Z',
          sort_by: 'admin_share',
          sort_direction: 'desc',
          work_role: 'implementation',
          harness: 'pi',
        }),
      ),
    )
    const link =
      screen
        .getByRole('link', { name: 'Work and admin activity across projects' })
        .getAttribute('href') ?? ''
    const scope = parseSessionListState(
      new URL(link, 'https://example.test').searchParams,
    )
    expect(scope).toMatchObject({
      accountingWindow: {
        start: '2026-10-21T12:00:00Z',
        end: '2026-10-22T12:00:00Z',
      },
      workRole: 'implementation',
      harness: 'pi',
      sort: 'admin_share',
    })
    fireEvent.change(screen.getByRole('combobox', { name: 'Sort' }), {
      target: { value: 'admin_duration' },
    })
    await waitFor(() =>
      expect(querySessions).toHaveBeenLastCalledWith(
        expect.objectContaining({
          cursor: undefined,
          sort_by: 'admin_duration',
          accounting_start: '2026-10-21T12:00:00Z',
          accounting_end: '2026-10-22T12:00:00Z',
        }),
      ),
    )
  })

  it('asks the server for recent root coding and chat sessions by default', async () => {
    mount()
    await screen.findByText('Fix the dispatcher retry loop')
    expect(querySessions).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: ['coding', 'chat'],
        roots_only: true,
        exclude_benchmarks: true,
        sort_by: 'last_active',
        sort_direction: 'desc',
        cursor: undefined,
        page_size: 100,
      }),
    )
    expect(screen.getByTestId('sessions-total-count')).toHaveTextContent(
      '2 matching',
    )
  })

  it('shows honest usage, sub-agent counts and the title fallback chain', async () => {
    mount()
    await screen.findByText('Fix the dispatcher retry loop')
    const rows = screen.getAllByTestId('session-row')
    expect(rows[0]).toHaveTextContent('120.0K / 4.5K')
    expect(rows[0]).toHaveTextContent('3')
    expect(rows[0]).not.toHaveTextContent('fallback')
    expect(rows[1]).toHaveTextContent('feature/sessions')
    expect(rows[1]).toHaveTextContent('not captured')
    expect(rows[1]).toHaveTextContent('claude code')
  })

  it('expands a row in place, pushing sel and loading its newest log window', async () => {
    vi.mocked(fetchSessionEvents).mockResolvedValue({
      session_id: codexRow.id,
      events: [
        {
          id: 'e1',
          turn: 1,
          sequence: 1,
          event_type: 'tool_use',
          role: null,
          content: null,
          tool_name: 'Bash',
          call_id: 'call-1',
          tool_input: { command: ['/bin/bash', '-lc', 'pytest -q tests/api'] },
          tool_output: null,
          tokens: null,
          duration_ms: null,
          model_used: null,
          agent_id: null,
          agent_name: null,
          created_at: '2026-10-10T08:00:00Z',
        },
        {
          id: 'e2',
          turn: 1,
          sequence: 2,
          event_type: 'tool_result',
          role: null,
          content: null,
          tool_name: null,
          call_id: 'call-1',
          tool_input: null,
          tool_output: {
            stdout: '3 passed',
            exit_code: 0,
            status: 'completed',
          },
          tokens: null,
          duration_ms: 3200,
          model_used: null,
          agent_id: null,
          agent_name: null,
          created_at: '2026-10-10T08:00:04Z',
        },
      ],
      total: 2,
      max_turn: 1,
      next_after: null,
    } as never)
    mount()
    fireEvent.click(await screen.findByText('Fix the dispatcher retry loop'))
    expect(nav.push).toHaveBeenCalledWith(
      expect.stringContaining(`&sel=${codexRow.id}`),
      {
        scroll: false,
      },
    )
    const panel = await screen.findByTestId('session-inline')
    // The panel sits directly after its row.
    const row = screen
      .getAllByTestId('session-row')
      .find((node) => node.getAttribute('data-session-id') === codexRow.id)
    expect(row).toHaveAttribute('aria-expanded', 'true')
    expect(row?.nextElementSibling).toBe(panel)
    expect(fetchSession).toHaveBeenCalledWith(codexRow.id, {
      includeEvents: false,
    })
    expect(fetchSessionEvents).toHaveBeenCalledWith(
      codexRow.id,
      expect.objectContaining({
        order: 'desc',
        page_size: 300,
        exclude_types: expect.arrayContaining([
          'child_session_update',
          'thinking',
        ]),
      }),
    )
    expect(await screen.findByText('pytest -q tests/api')).toBeInTheDocument()
    expect(screen.getByText('exit 0')).toBeInTheDocument()
    expect(screen.queryByText(/"exit_code"/)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Open/ })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Collapse session' }))
    expect(new URLSearchParams(nav.search).get('sel')).toBeNull()
    expect(new URLSearchParams(nav.search).get('accounting_end')).toBeTruthy()
  })

  it('restores filters and selection from the URL', async () => {
    nav.reset(`q=retry&status=failed&subagents=1&sel=${codexRow.id}`)
    mount()
    await screen.findByTestId('session-inline')
    expect(querySessions).toHaveBeenCalledWith(
      expect.objectContaining({
        q: 'retry',
        status: 'failed',
        roots_only: false,
      }),
    )
    expect(screen.getByLabelText('Search sessions')).toHaveValue('retry')
  })

  it('debounces search into a replaced URL entry', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      mount()
      await screen.findByText('Fix the dispatcher retry loop')
      fireEvent.change(screen.getByLabelText('Search sessions'), {
        target: { value: 'task-66a9' },
      })
      expect(new URLSearchParams(nav.search).get('q')).toBeNull()
      await act(async () => {
        vi.advanceTimersByTime(300)
      })
      expect(nav.replace).toHaveBeenCalledWith(
        expect.stringContaining('&q=task-66a9'),
        {
          scroll: false,
        },
      )
      expect(nav.push).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('shows facet counts and toggles kinds through the URL', async () => {
    mount()
    const completions = await screen.findByRole('button', {
      name: /Completions/,
    })
    await waitFor(() => expect(completions).toHaveTextContent('900'))
    expect(completions).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(completions)
    expect(nav.replace).toHaveBeenCalledWith(
      expect.stringContaining('&kind=coding%2Cchat%2Ccompletion'),
      { scroll: false },
    )
  })

  it('offers to clear filters when nothing matches', async () => {
    nav.reset('q=nothing-here')
    vi.mocked(querySessions).mockResolvedValue(listResponse([]))
    mount()
    expect(
      await screen.findByText('No sessions match these filters.'),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(new URLSearchParams(nav.search).get('q')).toBeNull()
    expect(new URLSearchParams(nav.search).get('accounting_start')).toBeTruthy()
  })

  it('shows a retryable error', async () => {
    vi.mocked(querySessions).mockRejectedValueOnce(new Error('boom'))
    mount()
    expect(await screen.findByText('Unable to load sessions')).toBeVisible()
    vi.mocked(querySessions).mockResolvedValue(listResponse([codexRow]))
    fireEvent.click(screen.getByRole('button', { name: /Retry/ }))
    expect(
      await screen.findByText('Fix the dispatcher retry loop'),
    ).toBeInTheDocument()
  })

  it('labels a partial list and pages with the server cursor', async () => {
    vi.mocked(querySessions).mockResolvedValueOnce(
      listResponse([codexRow], 'cursor-2'),
    )
    mount()
    expect(
      await screen.findByTestId('sessions-loaded-count'),
    ).toHaveTextContent('Partial: showing 1 of 101')
    vi.mocked(querySessions).mockResolvedValueOnce(listResponse([claudeRow]))
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }))
    await waitFor(() =>
      expect(screen.getAllByTestId('session-row')).toHaveLength(2),
    )
    expect(querySessions).toHaveBeenLastCalledWith(
      expect.objectContaining({ cursor: 'cursor-2' }),
    )
  })

  it('moves the row cursor with j/k but not while typing in search', async () => {
    mount()
    await screen.findByText('Fix the dispatcher retry loop')
    const [first, second] = screen.getAllByTestId('session-row')
    expect(first).toHaveAttribute('tabindex', '0')
    first.focus()
    fireEvent.keyDown(first, { key: 'j' })
    expect(second).toHaveAttribute('tabindex', '0')
    expect(document.activeElement).toBe(second)

    const search = screen.getByLabelText('Search sessions')
    search.focus()
    fireEvent.keyDown(search, { key: 'k' })
    expect(second).toHaveAttribute('tabindex', '0')

    second.focus()
    fireEvent.keyDown(second, { key: ' ' })
    expect(nav.push).toHaveBeenCalledWith(
      expect.stringContaining(`&sel=${claudeRow.id}`),
      {
        scroll: false,
      },
    )
  })
})

describe('session list URL state', () => {
  it('round-trips non-default state and omits defaults', () => {
    expect(serializeSessionListState(DEFAULT_LIST_STATE).toString()).toBe('')
    const state = {
      ...DEFAULT_LIST_STATE,
      q: 'abc',
      kinds: ['completion' as const],
      since: '7d' as const,
      project: 'summitflow',
      includeSubagents: true,
      sort: 'status' as const,
      selected: 'xyz',
    }
    const params = serializeSessionListState(state)
    expect(parseSessionListState(params)).toEqual(state)
  })

  it('ignores unknown values instead of producing an empty view', () => {
    const state = parseSessionListState(
      new URLSearchParams('kind=bogus&status=nope&sort=cost&since=1h'),
    )
    expect(state.kinds).toEqual(DEFAULT_LIST_STATE.kinds)
    expect(state.status).toBe('')
    expect(state.sort).toBe('last_active')
    expect(state.since).toBe('all')
  })
})

describe('session display helpers', () => {
  it('formats long durations with hours and days', () => {
    expect(formatDurationMs(950)).toBe('950ms')
    expect(formatDurationMs(90_000)).toBe('1m 30s')
    expect(formatDurationMs(3 * 3_600_000 + 5 * 60_000)).toBe('3h 5m')
    expect(formatDurationMs(50 * 3_600_000)).toBe('2d 2h')
  })

  it('does not report an unobserved Codex model as a fallback', () => {
    const identity = getExecutionIdentity(codexRow)
    expect(identity.effectiveModel).toBe('codex/gpt-5.5')
    expect(identity.fallbackUsed).toBe(false)
  })

  it('still reports a real fallback', () => {
    const identity = getExecutionIdentity(
      row({
        requested_model: 'claude-opus-5-5',
        effective_model: 'claude-sonnet-5-5',
        fallback_used: true,
      }),
    )
    expect(identity.fallbackUsed).toBe(true)
    expect(identity.showRequested).toBe(true)
  })

  it('prefers usage events, then message counters, then says not captured', () => {
    expect(getUsageSummary(codexRow).label).toBe('120.0K / 4.5K')
    expect(
      getUsageSummary(row({ total_input_tokens: 10, total_output_tokens: 5 }))
        .known,
    ).toBe(true)
    expect(getUsageSummary(claudeRow).label).toBe('not captured')
  })

  it('falls back from title to summary to branch to short id', () => {
    expect(getSessionTitle(row({ title: '  Hi  ' }))).toBe('Hi')
    expect(getSessionTitle(row({ summary_oneliner: 'sum' }))).toBe('sum')
    expect(getSessionTitle(row({ current_branch: 'main' }))).toBe('main')
    expect(getSessionTitle(row({}))).toBe('session aaaaaaaa')
  })
})
