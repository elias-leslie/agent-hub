import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ProjectPermission } from '@/lib/api'
import { fetchProjectPermissions, fetchProjectRoots } from '@/lib/api'
import { fetchProjectConfigs } from '../app/chat/hooks/useProjectContext'

vi.mock('@/lib/api', () => ({
  fetchProjectPermissions: vi.fn(),
  fetchProjectRoots: vi.fn(),
}))

const mockFetchProjectPermissions = vi.mocked(fetchProjectPermissions)
const mockFetchProjectRoots = vi.mocked(fetchProjectRoots)

function permission(
  projectId: string,
  rootPath: string | null,
): ProjectPermission {
  return {
    project_id: projectId,
    permission_tier: 'read',
    auto_exec_enabled: false,
    execution_start_hour: 0,
    execution_end_hour: 24,
    root_path: rootPath,
    updated_at: '2026-04-28T00:00:00Z',
    created_at: '2026-04-28T00:00:00Z',
  }
}

describe('fetchProjectConfigs', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('prefers canonical project roots over permission root paths', async () => {
    mockFetchProjectPermissions.mockResolvedValue([
      permission('agent-hub', '/home/kasadis/agent-hub'),
    ])
    mockFetchProjectRoots.mockResolvedValue({
      'agent-hub': '/srv/workspaces/projects/agent-hub',
    })

    await expect(fetchProjectConfigs()).resolves.toEqual([
      {
        id: 'agent-hub',
        name: 'Agent Hub',
        rootPath: '/srv/workspaces/projects/agent-hub',
      },
    ])
  })

  it('falls back to permission root path when no canonical root exists', async () => {
    mockFetchProjectPermissions.mockResolvedValue([
      permission('external-project', '/tmp/external-project'),
    ])
    mockFetchProjectRoots.mockResolvedValue({})

    await expect(fetchProjectConfigs()).resolves.toEqual([
      {
        id: 'external-project',
        name: 'External Project',
        rootPath: '/tmp/external-project',
      },
    ])
  })
})
