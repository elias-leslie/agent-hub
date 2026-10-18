import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  fetchSessionCloseSettings,
  updateSessionCloseSettings,
} from '@/lib/api/sessions'
import { CloseSettingsPanel } from './CloseSettingsPanel'

vi.mock('@/lib/api/sessions', () => ({
  fetchSessionCloseSettings: vi.fn(),
  updateSessionCloseSettings: vi.fn(),
}))

const SETTINGS = {
  dead_candidate_after_minutes: 30,
  reapable_after_minutes: 360,
  zero_event_close_after_minutes: 60,
  transcript_sync_close_after_minutes: 60,
  completion_close_after_minutes: 240,
  any_session_close_after_minutes: 1440,
  codex_close_inactive_enabled: true,
  codex_scan_hours: 24,
  updated_by: null,
}

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <CloseSettingsPanel onClose={() => {}} />
    </QueryClientProvider>,
  )
}

describe('CloseSettingsPanel', () => {
  beforeEach(() => {
    vi.mocked(fetchSessionCloseSettings).mockResolvedValue(SETTINGS)
  })

  it('saves only the changed settings', async () => {
    vi.mocked(updateSessionCloseSettings).mockResolvedValue({
      ...SETTINGS,
      reapable_after_minutes: 120,
      codex_close_inactive_enabled: false,
    })
    renderPanel()
    const quiet = await screen.findByLabelText('Close quiet sessions after')
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()

    fireEvent.change(quiet, { target: { value: '120' } })
    fireEvent.click(
      screen.getByLabelText('Close Codex sessions when Codex exits'),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(updateSessionCloseSettings).toHaveBeenCalledWith({
        reapable_after_minutes: 120,
        codex_close_inactive_enabled: false,
      }),
    )
    expect(await screen.findByText(/Saved\./)).toBeInTheDocument()
  })

  it('shows the server refusal', async () => {
    vi.mocked(updateSessionCloseSettings).mockRejectedValue(
      new Error(
        'Close any session must be at least as long as Close completions.',
      ),
    )
    renderPanel()
    const any = await screen.findByLabelText('Close any session after')
    fireEvent.change(any, { target: { value: '120' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(
      await screen.findByText(/Not saved: Close any session/),
    ).toBeInTheDocument()
  })
})
