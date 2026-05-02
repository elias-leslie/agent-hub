import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSessionExpansion } from '@/app/sessions/hooks/useSessionExpansion'
import SessionsPage from '@/app/sessions/page'
import { createQueryClientWrapper } from './test-utils'

vi.mock('@/components/chat/use-models', () => ({
  useModels: () => [],
}))

vi.mock('@/components/timeline', () => ({
  EventTimeline: ({ events }: { events: Array<unknown> }) => (
    <div data-testid="event-timeline">{events.length} events</div>
  ),
}))

vi.mock('@/lib/api', () => ({
  fetchSessions: vi.fn(),
  fetchSession: vi.fn(),
  fetchAllSessionEvents: vi.fn(),
}))

import { fetchAllSessionEvents, fetchSession, fetchSessions } from '@/lib/api'

const mockSessions = {
  sessions: [
    {
      id: 'session-123-abc',
      project_id: 'test-project',
      provider: 'claude',
      model: 'claude-sonnet-4-6',
      requested_provider: 'claude',
      requested_model: 'claude-opus-4-7',
      effective_provider: 'claude',
      effective_model: 'claude-sonnet-4-6',
      fallback_used: true,
      fallback_reason: 'rate_limit',
      status: 'active',
      agent_slug: 'code_generation',
      session_type: 'completion',
      summary_oneliner: 'dispatch parser cleared branch drift',
      live_activity: {
        phase: 'tool',
        status: 'running',
        health: 'healthy',
        stalled: false,
        outstanding_tool_calls: 0,
        tool_calls_count: 3,
        files_touched: [],
        lifecycle_state: 'working',
        lifecycle_reason_codes: [],
        dead_signals: [],
        anti_reap_signals: [],
        has_owner_lane: true,
        has_specialist_lane: false,
        reapable: false,
      },
      message_count: 5,
      event_count: 12,
      total_input_tokens: 1500,
      total_output_tokens: 800,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-07T10:00:00Z',
    },
    {
      id: 'session-456-def',
      project_id: 'test-project',
      provider: 'gemini',
      model: 'gemini-3-flash',
      requested_provider: 'gemini',
      requested_model: 'gemini-3-flash',
      effective_provider: 'gemini',
      effective_model: 'gemini-3-flash',
      fallback_used: false,
      fallback_reason: null,
      status: 'completed',
      agent_slug: null,
      session_type: 'chat',
      summary_oneliner: 'verification passed cleanly',
      message_count: 10,
      event_count: 20,
      total_input_tokens: 3200,
      total_output_tokens: 1200,
      created_at: '2026-01-02T00:00:00Z',
      updated_at: '2026-01-06T15:00:00Z',
    },
  ],
  total: 2,
  page: 1,
  page_size: 20,
}

function renderPage() {
  return render(<SessionsPage />, { wrapper: createQueryClientWrapper() })
}

function createDeferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe('SessionsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchSessions).mockResolvedValue(mockSessions)
    vi.mocked(fetchSession).mockResolvedValue({
      id: 'session-123-abc',
      project_id: 'test-project',
      provider: 'claude',
      model: 'claude-sonnet-4-6',
      requested_provider: 'claude',
      requested_model: 'claude-opus-4-7',
      effective_provider: 'claude',
      effective_model: 'claude-sonnet-4-6',
      fallback_used: true,
      fallback_reason: 'rate_limit',
      status: 'active',
      agent_slug: 'code_generation',
      session_type: 'completion',
      live_activity: null,
      messages: [],
      context_usage: null,
      agent_token_breakdown: [],
      message_count: 5,
      event_count: 12,
      total_input_tokens: 1500,
      total_output_tokens: 800,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-07T10:00:00Z',
    })
    vi.mocked(fetchAllSessionEvents).mockResolvedValue({
      session_id: 'session-123-abc',
      events: [],
      total: 12,
      max_turn: 3,
    })
  })

  it('shows explicit visible, loaded, and total counts in the ledger header', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByTestId('sessions-visible-count')).toHaveTextContent(
        '2',
      )
      expect(screen.getByTestId('sessions-loaded-count')).toHaveTextContent('2')
      expect(screen.getByTestId('sessions-total-count')).toHaveTextContent('2')
    })

    expect(screen.getByTestId('sessions-filter-scope')).toHaveTextContent(
      /2\s+visible\s*·\s*2\s+loaded\s*·\s*2\s+total/i,
    )
  })

  it('updates visible count when search filters the loaded subset', async () => {
    renderPage()

    await waitFor(() => {
      expect(
        screen.getByText('dispatch parser cleared branch drift'),
      ).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText(/search loaded rows/i), {
      target: { value: '456' },
    })

    await waitFor(() => {
      expect(screen.getByTestId('sessions-visible-count')).toHaveTextContent(
        '1',
      )
      expect(screen.getByTestId('sessions-loaded-count')).toHaveTextContent('2')
      expect(screen.getByTestId('sessions-total-count')).toHaveTextContent('2')
    })
  })

  it('surfaces effective model identity, fallback state, and compact message/event counts', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByText(/claude\/sonnet-4\.6/i)).toBeInTheDocument()
      expect(screen.getByText(/^fallback$/i)).toBeInTheDocument()
      expect(screen.getByText(/5 msg/i)).toBeInTheDocument()
      expect(screen.getByText(/12 evt/i)).toBeInTheDocument()
    })
  })

  it('shows a live usage placeholder instead of blank dashes for active zero-token rows', async () => {
    vi.mocked(fetchSessions).mockResolvedValue({
      ...mockSessions,
      sessions: [
        {
          ...mockSessions.sessions[0],
          total_input_tokens: 0,
          total_output_tokens: 0,
        },
      ],
      total: 1,
    })

    renderPage()

    await waitFor(() => {
      expect(screen.getByText(/^collecting$/i)).toBeInTheDocument()
      expect(screen.queryByText(/^usage pending$/i)).not.toBeInTheDocument()
    })
  })

  it('keeps active asymmetric token rows visibly live instead of rendering them as final accounting', async () => {
    vi.mocked(fetchSessions).mockResolvedValue({
      ...mockSessions,
      sessions: [
        {
          ...mockSessions.sessions[0],
          total_input_tokens: 0,
          total_output_tokens: 631,
        },
      ],
      total: 1,
    })

    renderPage()

    await waitFor(() => {
      expect(screen.getByText(/^live · in 0 · out 631$/i)).toBeInTheDocument()
      expect(screen.queryByText(/^usage pending$/i)).not.toBeInTheDocument()
    })
  })

  it('shows explicit zero usage for completed zero-token rows', async () => {
    vi.mocked(fetchSessions).mockResolvedValue({
      ...mockSessions,
      sessions: [
        {
          ...mockSessions.sessions[1],
          agent_slug: 'reviewer',
          total_input_tokens: 0,
          total_output_tokens: 0,
        },
      ],
      total: 1,
    })

    renderPage()

    await waitFor(() => {
      expect(screen.getByText(/^in 0 · out 0$/i)).toBeInTheDocument()
    })
  })

  it('expands from the row body while keeping nested controls isolated', async () => {
    renderPage()

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /expand session session-123-abc/i }),
      ).toBeInTheDocument()
      expect(
        screen.getByRole('button', { name: /filter model claude-sonnet-4-6/i }),
      ).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('dispatch parser cleared branch drift'))

    await waitFor(() => {
      expect(fetchSession).toHaveBeenCalledWith('session-123-abc')
      expect(screen.getByText(/5 messages · 12 events/i)).toBeInTheDocument()
      expect(screen.getByTestId('event-timeline')).toHaveTextContent('0 events')
    })

    fireEvent.click(
      screen.getByRole('button', { name: /filter model claude-sonnet-4-6/i }),
    )

    expect(fetchSession).toHaveBeenCalledTimes(1)
    expect(screen.getByText(/5 messages · 12 events/i)).toBeInTheDocument()
    expect(screen.getByTestId('event-timeline')).toBeInTheDocument()
  })

  it('shows a no-match state when the current filters remove every loaded row', async () => {
    renderPage()

    await waitFor(() => {
      expect(
        screen.getByText('dispatch parser cleared branch drift'),
      ).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText(/search loaded rows/i), {
      target: { value: 'no-match' },
    })

    await waitFor(() => {
      expect(
        screen.getByText(/no loaded rows match the current filters/i),
      ).toBeInTheDocument()
    })
  })

  it('keeps a load-more cue available when filters hide all loaded rows but more pages remain', async () => {
    vi.mocked(fetchSessions)
      .mockResolvedValueOnce({
        ...mockSessions,
        total: 30,
        page_size: 25,
      })
      .mockResolvedValueOnce({
        sessions: [],
        total: 30,
        page: 2,
        page_size: 25,
      })

    renderPage()

    await waitFor(() => {
      expect(
        screen.getByText('dispatch parser cleared branch drift'),
      ).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText(/search loaded rows/i), {
      target: { value: 'no-match' },
    })

    await waitFor(() => {
      expect(
        screen.getByText(/search only covers the 2 loaded rows/i),
      ).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /load more results/i }))

    await waitFor(() => {
      expect(fetchSessions).toHaveBeenCalledTimes(2)
    })
  })

  it('clears expanded row state and returns focus to search when filters hide the active row', async () => {
    vi.mocked(fetchSessions).mockResolvedValue(mockSessions)

    renderPage()

    await waitFor(() => {
      expect(
        screen.getByText('dispatch parser cleared branch drift'),
      ).toBeInTheDocument()
    })

    fireEvent.click(
      screen.getByRole('button', { name: /expand session session-123-abc/i }),
    )

    await waitFor(() => {
      expect(
        screen.getByRole('button', {
          name: /collapse session session-123-abc/i,
        }),
      ).toBeInTheDocument()
    })

    fireEvent.click(
      screen.getByRole('button', { name: /filter model gemini-3-flash/i }),
    )

    await waitFor(() => {
      expect(
        screen.queryByText('dispatch parser cleared branch drift'),
      ).not.toBeInTheDocument()
    })

    expect(screen.getByPlaceholderText(/search loaded rows/i)).toHaveFocus()

    fireEvent.click(
      screen.getByRole('button', { name: /filter model gemini-3-flash/i }),
    )

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /expand session session-123-abc/i }),
      ).toBeInTheDocument()
    })

    expect(
      screen.queryByRole('button', {
        name: /collapse session session-123-abc/i,
      }),
    ).not.toBeInTheDocument()
  })

  it('shows an empty-data state when the server returns no sessions', async () => {
    vi.mocked(fetchSessions).mockResolvedValue({
      sessions: [],
      total: 0,
      page: 1,
      page_size: 20,
    })

    renderPage()

    await waitFor(() => {
      expect(screen.getByText(/no sessions loaded\./i)).toBeInTheDocument()
    })
  })

  it('shows a retryable error state when the sessions query fails', async () => {
    vi.mocked(fetchSessions)
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce(mockSessions)

    renderPage()

    await waitFor(() => {
      expect(
        screen.getByText(/unable to load sessions ledger/i),
      ).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /retry sessions/i }))

    await waitFor(() => {
      expect(fetchSessions).toHaveBeenCalledTimes(2)
      expect(
        screen.getByText('dispatch parser cleared branch drift'),
      ).toBeInTheDocument()
    })
  })

  it('keeps row context visible and shows a local evidence error when detail fetch fails', async () => {
    vi.mocked(fetchSession).mockRejectedValueOnce(new Error('detail boom'))
    vi.mocked(fetchAllSessionEvents).mockRejectedValueOnce(
      new Error('detail boom'),
    )

    renderPage()

    await waitFor(() => {
      expect(
        screen.getByText('dispatch parser cleared branch drift'),
      ).toBeInTheDocument()
    })

    fireEvent.click(
      screen.getByRole('button', { name: /expand session session-123-abc/i }),
    )

    await waitFor(() => {
      expect(
        screen.getByText(/session evidence unavailable/i),
      ).toBeInTheDocument()
    })

    expect(
      screen.getByText('dispatch parser cleared branch drift'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText(/unable to load sessions ledger/i),
    ).not.toBeInTheDocument()
  })
})

describe('useSessionExpansion', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('drops stale expansion responses and preserves the most recently requested session', async () => {
    const aSession = createDeferred<{ id: string }>()
    const aEvents = createDeferred<{
      session_id: string
      events: Array<unknown>
      total: number
      max_turn: number
    }>()
    const bSession = createDeferred<{ id: string }>()
    const bEvents = createDeferred<{
      session_id: string
      events: Array<unknown>
      total: number
      max_turn: number
    }>()

    vi.mocked(fetchSession).mockImplementation((sessionId: string) => {
      if (sessionId === 'session-a') {
        return aSession.promise as never
      }
      return bSession.promise as never
    })

    vi.mocked(fetchAllSessionEvents).mockImplementation((sessionId: string) => {
      if (sessionId === 'session-a') {
        return aEvents.promise as never
      }
      return bEvents.promise as never
    })

    const { result } = renderHook(() => useSessionExpansion())

    await act(async () => {
      void result.current.handleToggleExpand('session-a')
      void result.current.handleToggleExpand('session-b')
    })

    await act(async () => {
      bSession.resolve({ id: 'session-b' })
      bEvents.resolve({
        session_id: 'session-b',
        events: [],
        total: 0,
        max_turn: 0,
      })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(result.current.expandedSessionId).toBe('session-b')
      expect(result.current.expandedSessionData).toEqual({ id: 'session-b' })
      expect(result.current.expandedEventsData).toEqual({
        session_id: 'session-b',
        events: [],
        total: 0,
        max_turn: 0,
      })
      expect(result.current.isLoadingDetails).toBe(false)
    })

    await act(async () => {
      aSession.resolve({ id: 'session-a' })
      aEvents.resolve({
        session_id: 'session-a',
        events: [],
        total: 0,
        max_turn: 0,
      })
      await Promise.resolve()
    })

    expect(result.current.expandedSessionId).toBe('session-b')
    expect(result.current.expandedSessionData).toEqual({ id: 'session-b' })
    expect(result.current.expandedEventsData).toEqual({
      session_id: 'session-b',
      events: [],
      total: 0,
      max_turn: 0,
    })
  })

  it('clears both session and evidence data when expansion is cleared', async () => {
    vi.mocked(fetchSession).mockResolvedValue({ id: 'session-a' } as never)
    vi.mocked(fetchAllSessionEvents).mockResolvedValue({
      session_id: 'session-a',
      events: [],
      total: 0,
      max_turn: 0,
    } as never)

    const { result } = renderHook(() => useSessionExpansion())

    await act(async () => {
      await result.current.handleToggleExpand('session-a')
    })

    expect(result.current.expandedSessionData).toEqual({ id: 'session-a' })
    expect(result.current.expandedEventsData).toEqual({
      session_id: 'session-a',
      events: [],
      total: 0,
      max_turn: 0,
    })

    act(() => {
      result.current.clearExpansion()
    })

    expect(result.current.expandedSessionId).toBeNull()
    expect(result.current.expandedSessionData).toBeNull()
    expect(result.current.expandedEventsData).toBeNull()
  })
})
