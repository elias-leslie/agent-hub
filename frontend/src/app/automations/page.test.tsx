import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  fetchAutomationPolicy,
  fetchAutomationProfiles,
  fetchAutomationRegistry,
  fetchAutomationRuns,
} from '@/lib/api/automations'
import { fetchProjectCatalog } from '@/lib/api/project-permissions'
import AutomationsPage from './page'

vi.mock('@/lib/api/automations', () => ({
  fetchAutomationPolicy: vi.fn(),
  fetchAutomationProfiles: vi.fn(),
  fetchAutomationRegistry: vi.fn(),
  fetchAutomationRuns: vi.fn(),
  createAutomationProfile: vi.fn(),
  updateAutomationProfile: vi.fn(),
  updateAutomationPolicy: vi.fn(),
  reviewAutomationProfile: vi.fn(),
  runAutomationProfile: vi.fn(),
}))
vi.mock('@/lib/api/project-permissions', () => ({
  fetchProjectCatalog: vi.fn(),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('Automations project policy', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.history.replaceState({}, '', '/automations?project_id=agent-hub')
    vi.mocked(fetchProjectCatalog).mockResolvedValue([
      {
        project_id: 'agent-hub',
        label: 'Agent Hub',
        root_path: null,
        has_permission: true,
        has_root: false,
        has_memory: false,
        sources: ['permission'],
      },
    ])
    vi.mocked(fetchAutomationRegistry).mockResolvedValue({ definitions: [] })
    vi.mocked(fetchAutomationProfiles).mockResolvedValue({
      items: [],
      total: 0,
    })
    vi.mocked(fetchAutomationPolicy).mockResolvedValue({
      project_id: 'agent-hub',
      enabled: true,
      config: {},
      revision: 1,
      sync_revision: 0,
      sync_pending: false,
      updated_at: null,
    })
  })

  it('shows the central policy without a per-project execution section', async () => {
    render(<AutomationsPage />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: 'Project policy' }))
    await waitFor(() => {
      expect(fetchAutomationPolicy).toHaveBeenCalledWith('agent-hub')
    })
    expect(
      screen.queryByRole('heading', { name: 'Execution permission' }),
    ).not.toBeInTheDocument()
  })

  it('names runs by their profile and keeps the workflow key in the details', async () => {
    vi.mocked(fetchAutomationProfiles).mockResolvedValue({
      items: [
        {
          id: 'p1',
          project_id: 'agent-hub',
          subject_id: null,
          workflow_key: 'agent-hub.session_cleanup',
          definition_version: 1,
          label: 'Session cleanup',
          schedule_type: 'cron',
          schedule_value: '*/15 * * * *',
          schedule_timezone: 'UTC',
          config: {},
          enabled: true,
          effective_enabled: true,
          gate_reasons: [],
          clock_owner: 'central',
          next_run_at: null,
          last_run_at: null,
          unreviewed_count: 0,
          last_reviewed_at: null,
          revision: 1,
        },
      ],
      total: 1,
    })
    vi.mocked(fetchAutomationRuns).mockResolvedValue({
      items: [
        {
          id: 'r1',
          profile_id: 'p1',
          project_id: 'agent-hub',
          workflow_key: 'agent-hub.session_cleanup',
          definition_version: 1,
          profile_revision: 1,
          occurrence_key: 'o1',
          scheduled_for: null,
          status: 'succeeded',
          trigger: 'scheduled',
          gate_reasons: [],
          created_at: '2026-10-29T21:45:02Z',
        },
        {
          id: 'r2',
          profile_id: 'gone',
          project_id: 'agent-hub',
          workflow_key: 'agent-hub.session_reaper',
          definition_version: 1,
          profile_revision: 1,
          occurrence_key: 'o2',
          scheduled_for: null,
          status: 'succeeded',
          trigger: 'scheduled',
          gate_reasons: [],
          created_at: '2026-10-29T21:30:02Z',
        },
      ],
      total: 2,
    })
    render(<AutomationsPage />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: 'Run history' }))
    const named = await screen.findByText('Session cleanup', {
      selector: 'summary span',
    })
    expect(named).toBeInTheDocument()
    expect(screen.getByText('agent-hub.session_cleanup')).toBeInTheDocument()
    expect(
      screen.getByText('agent-hub.session_reaper', {
        selector: 'summary span',
      }),
    ).toBeInTheDocument()
  })
})
