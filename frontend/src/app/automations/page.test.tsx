import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  fetchAutomationPolicy,
  fetchAutomationProfiles,
  fetchAutomationRegistry,
} from '@/lib/api/automations'
import {
  fetchProjectCatalog,
  fetchProjectPermission,
  updateProjectPermission,
} from '@/lib/api/project-permissions'
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
  fetchProjectPermission: vi.fn(),
  updateProjectPermission: vi.fn(),
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
    vi.mocked(fetchProjectPermission).mockResolvedValue({
      project_id: 'agent-hub',
      permission_tier: 'full',
      auto_exec_enabled: true,
      execution_start_hour: 0,
      execution_end_hour: 24,
      root_path: null,
      updated_at: '2026-09-23T00:00:00Z',
      created_at: '2026-09-23T00:00:00Z',
    })
    vi.mocked(updateProjectPermission).mockResolvedValue({
      project_id: 'agent-hub',
      permission_tier: 'full',
      auto_exec_enabled: false,
      execution_start_hour: 0,
      execution_end_hour: 24,
      root_path: null,
      updated_at: '2026-09-23T01:00:00Z',
      created_at: '2026-09-23T00:00:00Z',
    })
  })

  it('saves execution permission from the central policy tab', async () => {
    render(<AutomationsPage />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: 'Project policy' }))
    await screen.findByRole('heading', { name: 'Execution permission' })
    expect(fetchProjectPermission).toHaveBeenCalledWith('agent-hub')
    fireEvent.click(
      screen.getByRole('checkbox', { name: 'Allow automated execution' }),
    )
    fireEvent.click(
      screen.getByRole('button', { name: 'Save execution permission' }),
    )
    await waitFor(() => {
      expect(updateProjectPermission).toHaveBeenCalledWith('agent-hub', {
        auto_exec_enabled: false,
        execution_start_hour: 0,
        execution_end_hour: 24,
      })
    })
  })
})
