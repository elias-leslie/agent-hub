import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ProjectPermissionsPage from '@/app/access-control/permissions/page'
import {
  createProjectPermission,
  fetchProjectPermissions,
  updateProjectPermission,
} from '@/lib/api'

vi.mock('@/lib/api', () => ({
  createProjectPermission: vi.fn(),
  fetchProjectPermissions: vi.fn(),
  updateProjectPermission: vi.fn(),
}))

const mockPermissions = [
  {
    project_id: 'agent-hub',
    permission_tier: 'full' as const,
    auto_exec_enabled: true,
    execution_start_hour: 0,
    execution_end_hour: 24,
    root_path: '/srv/workspaces/projects/agent-hub',
    updated_at: '2026-03-26T00:00:00Z',
    created_at: '2026-03-26T00:00:00Z',
  },
]

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
  }
}

describe('ProjectPermissionsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(fetchProjectPermissions).mockResolvedValue(mockPermissions)
    vi.mocked(createProjectPermission).mockResolvedValue({
      ...mockPermissions[0],
      project_id: 'test2',
      root_path: '/srv/workspaces/projects/test2',
    })
    vi.mocked(updateProjectPermission).mockResolvedValue(mockPermissions[0])
  })

  it('creates a new project permission from the form', async () => {
    render(<ProjectPermissionsPage />, { wrapper: createWrapper() })

    await waitFor(() => {
      expect(screen.getByText('Project Permissions')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText('test2'), {
      target: { value: 'test2' },
    })
    fireEvent.change(screen.getByDisplayValue('Read'), {
      target: { value: 'full' },
    })
    fireEvent.click(screen.getByLabelText('Auto Exec'))
    fireEvent.click(screen.getByRole('button', { name: 'Add Project' }))

    await waitFor(() => {
      expect(createProjectPermission).toHaveBeenCalled()
    })

    expect(vi.mocked(createProjectPermission).mock.calls[0]?.[0]).toEqual({
      project_id: 'test2',
      permission_tier: 'full',
      auto_exec_enabled: true,
    })
  })
})
