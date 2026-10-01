import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { Suspense } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SessionDetailPage from '@/app/sessions/[id]/page'
import { fetchAllSessionEvents, fetchSession } from '@/lib/api'
import { fetchNativeCaptureStatus } from '@/lib/api/native-capture'
import { fetchNativeEvidenceSummary } from '@/lib/api/native-evidence'

vi.mock('next/navigation', () => ({
  usePathname: () => '/sessions/session',
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/lib/api', () => ({
  fetchSession: vi.fn(),
  fetchAllSessionEvents: vi.fn(),
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
    vi.mocked(fetchAllSessionEvents).mockResolvedValue(events)
    await mount()
    expect(await screen.findByText('Toy recorded history')).toBeInTheDocument()
    expect(
      screen.getByText(/Session details are unavailable/),
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
    vi.mocked(fetchAllSessionEvents).mockResolvedValue(events)
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
})
