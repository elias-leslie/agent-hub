import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  fetchAutomationPolicy,
  fetchAutomationProfiles,
  fetchAutomationRegistry,
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
})
