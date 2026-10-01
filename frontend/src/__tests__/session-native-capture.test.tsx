import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NativeCapture } from '@/app/sessions/[id]/components/NativeCapture'
import type { Session } from '@/lib/api'
import {
  fetchNativeCaptureStatus,
  parseNativeCaptureStatus,
} from '@/lib/api/native-capture'

vi.mock('@/lib/api/native-capture', async (original) => ({
  ...(await original<typeof import('@/lib/api/native-capture')>()),
  fetchNativeCaptureStatus: vi.fn(),
}))

const status = {
  schema_version: 'native-observation.v1',
  session_id: 'session',
  capture_mode: 'app_server_registered',
  projection_authority: 'rollout',
  promotion_state: 'shadow',
  observed_model: null,
  promotion_requested: false,
  promotion_eligible: false,
  promotion_blockers: ['canonical_ordering_unproven'],
  delivery_status: 'collector_reported_only',
  sources: [
    {
      source_id: 'source',
      kind: 'app_server',
      provider_version: '0.159.2',
      schema_fingerprint: 'fingerprint',
      authenticity: 'collector_attested',
      committed_position: 0,
      receipt_count: 0,
      max_position: 0,
      first_missing_position: null,
      issues: {},
      protocol_supported: false,
      generation: 0,
      freshness: 'stale',
      last_received_at: '2026-10-01T12:00:00Z',
      dispositions: { unsupported: 2 },
      capture_health: { state: 'disabled', capture_gaps: 0 },
    },
  ],
}

const session = {
  id: 'session',
  provider: 'codex',
  model: 'configured-model',
  requested_model: 'requested-model',
  status: 'completed',
} as Session

function mount() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <NativeCapture session={session} />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.clearAllMocks())

describe('content-free native capture status', () => {
  it('selects health fields without retaining arbitrary raw evidence', () => {
    const parsed = parseNativeCaptureStatus({
      ...status,
      raw_payload: 'secret',
      sources: [
        {
          ...status.sources[0],
          raw_payload: 'secret',
          capture_health: {
            state: 'disabled',
            capture_gaps: 0,
            content: 'secret',
          },
        },
      ],
    })
    expect(JSON.stringify(parsed)).not.toContain('secret')
    expect(parsed.sources[0].capture_health?.capture_gaps).toBe(0)
    expect(() =>
      parseNativeCaptureStatus({
        ...status,
        sources: [{ ...status.sources[0], receipt_count: -1 }],
      }),
    ).toThrow('incompatible')
  })

  it('keeps configured and observed model separate and reports stale fallback evidence', async () => {
    vi.mocked(fetchNativeCaptureStatus).mockResolvedValue(
      parseNativeCaptureStatus(status),
    )
    mount()
    expect(await screen.findAllByText('Unknown')).toHaveLength(2)
    expect(screen.getByText('requested-model')).toBeInTheDocument()
    expect(
      screen.getByText('Protocol incompatible; rollout fallback'),
    ).toBeInTheDocument()
    expect(screen.getByText('Session runtime 0.159.2')).toBeInTheDocument()
    expect(screen.getByText('Stale')).toBeInTheDocument()
    expect(screen.getByText('0 / 2')).toBeInTheDocument()
    expect(screen.queryByText('secret')).not.toBeInTheDocument()
  })

  it('exposes a retry without changing available session history on health failure', async () => {
    vi.mocked(fetchNativeCaptureStatus)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(
        parseNativeCaptureStatus({ ...status, sources: [] }),
      )
    mount()
    expect(
      await screen.findByText(/Recorded session history remains available/),
    ).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', { name: 'Refresh capture health' }),
    )
    expect(
      await screen.findByText(/No native observation sources are registered/),
    ).toBeInTheDocument()
  })
})
