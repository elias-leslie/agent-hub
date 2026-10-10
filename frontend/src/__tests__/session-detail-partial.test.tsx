import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { Suspense } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SessionDetailPage from '@/app/sessions/[id]/page'
import { fetchNativeCaptureStatus } from '@/lib/api/native-capture'
import { fetchNativeEvidenceSummary } from '@/lib/api/native-evidence'
import {
  fetchSession,
  fetchSessionEvents,
  fetchSessionEventsSummary,
} from '@/lib/api/sessions'

vi.mock('next/navigation', () => ({
  usePathname: () => '/sessions/session',
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/lib/api/sessions', async (original) => ({
  ...(await original<typeof import('@/lib/api/sessions')>()),
  fetchSession: vi.fn(),
  fetchSessionEvents: vi.fn(),
  fetchSessionEventsSummary: vi.fn(),
  querySessions: vi.fn(),
}))
vi.mock('@/lib/api/native-capture', () => ({
  fetchNativeCaptureStatus: vi.fn(),
}))
vi.mock('@/lib/api/native-evidence', async (original) => ({
  ...(await original<typeof import('@/lib/api/native-evidence')>()),
  fetchNativeEvidenceSummary: vi.fn(),
}))

async function mount() {
  const params = Promise.resolve({ id: 'session' })
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

afterEach(() => vi.clearAllMocks())

describe('partial session detail requests', () => {
  const events = {
    session_id: 'session',
    total: 1,
    max_turn: 1,
    next_after: null,
    events: [
      {
        id: 'event',
        turn: 1,
        sequence: 1,
        event_type: 'assistant_message' as const,
        role: 'assistant',
        content: 'Toy recorded history',
        tool_name: null,
        tool_input: null,
        tool_output: null,
        tokens: null,
        duration_ms: null,
        model_used: null,
        agent_id: null,
        agent_name: null,
        created_at: '2026-10-01T12:00:00Z',
      },
    ],
  }

  it('keeps recorded history visible when session details fail', async () => {
    vi.mocked(fetchSession).mockRejectedValue(new Error('offline'))
    vi.mocked(fetchSessionEvents).mockResolvedValue(events)
    vi.mocked(fetchSessionEventsSummary).mockResolvedValue({
      total: 1,
      by_type: { assistant_message: 1 },
    })
    await mount()
    expect(await screen.findByText('Toy recorded history')).toBeInTheDocument()
    expect(
      screen.getByText(/Session details are unavailable/),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Retry' })).toHaveLength(1)
  })

  it('keeps history visible when the events summary fails and labels counts as loaded only', async () => {
    vi.mocked(fetchSession).mockRejectedValue(new Error('offline'))
    vi.mocked(fetchSessionEvents).mockResolvedValue(events)
    vi.mocked(fetchSessionEventsSummary).mockRejectedValue(
      new Error('summary down'),
    )
    await mount()
    expect(await screen.findByText('Toy recorded history')).toBeInTheDocument()
    expect(
      screen.getByText(/Chip counts cover loaded events only/),
    ).toBeInTheDocument()
  })

  it('keeps history visible when capture health and provenance fail', async () => {
    vi.mocked(fetchSession).mockResolvedValue({
      id: 'session',
      provider: 'codex',
      model: 'configured',
      status: 'completed',
      project_id: 'project',
      agent_slug: null,
      session_type: 'native',
      created_at: '2026-10-01T12:00:00Z',
      updated_at: '2026-10-01T12:00:00Z',
    })
    vi.mocked(fetchSessionEvents).mockResolvedValue(events)
    vi.mocked(fetchSessionEventsSummary).mockResolvedValue({
      total: 1,
      by_type: { assistant_message: 1 },
    })
    vi.mocked(fetchNativeCaptureStatus).mockRejectedValue(
      new Error('health unavailable'),
    )
    vi.mocked(fetchNativeEvidenceSummary).mockRejectedValue(
      new Error('evidence unavailable'),
    )
    await mount()
    expect(await screen.findByText('Toy recorded history')).toBeInTheDocument()
    expect(
      await screen.findByText(/Capture health is unavailable/),
    ).toBeInTheDocument()
    expect(
      await screen.findByText(/Evidence summary unavailable/),
    ).toBeInTheDocument()
  })

  it('shows an error with retry when history fails', async () => {
    vi.mocked(fetchSession).mockRejectedValue(new Error('offline'))
    vi.mocked(fetchSessionEvents).mockRejectedValue(new Error('offline'))
    vi.mocked(fetchSessionEventsSummary).mockRejectedValue(new Error('x'))
    await mount()
    expect(
      await screen.findByText('Session history is unavailable.'),
    ).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Retry' })).toHaveLength(2)
  })
})
