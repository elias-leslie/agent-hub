/**
 * Project permissions API module.
 *
 * Manages centralized automation access control for all projects.
 */

import { buildApiUrl, fetchApi } from '../api-config'

export interface ProjectPermission {
  project_id: string
  permission_tier: 'off' | 'read' | 'full'
  auto_exec_enabled: boolean
  execution_start_hour: number
  execution_end_hour: number
  root_path: string | null
  updated_at: string
  created_at: string
}

export interface ProjectPermissionUpdate {
  permission_tier?: 'off' | 'read' | 'full'
  auto_exec_enabled?: boolean
  execution_start_hour?: number
  execution_end_hour?: number
  root_path?: string | null
}

export interface ProjectPermissionCreate {
  project_id: string
  permission_tier?: 'off' | 'read' | 'full'
  auto_exec_enabled?: boolean
  execution_start_hour?: number
  execution_end_hour?: number
  root_path?: string | null
}

export interface ExecutionPermission {
  allowed: boolean
  permission_tier: string
  auto_exec_enabled: boolean
  in_time_window: boolean
  reason: string
}

export type ProjectRoots = Record<string, string>

export async function fetchProjectPermissions(): Promise<ProjectPermission[]> {
  const res = await fetchApi(buildApiUrl('/api/projects/permissions'))
  if (!res.ok) throw new Error('Failed to fetch project permissions')
  return res.json()
}

export async function fetchProjectRoots(): Promise<ProjectRoots> {
  const res = await fetchApi(buildApiUrl('/api/projects/roots'))
  if (!res.ok) throw new Error('Failed to fetch project roots')
  return res.json()
}

export async function updateProjectPermission(
  projectId: string,
  update: ProjectPermissionUpdate,
): Promise<ProjectPermission> {
  const res = await fetchApi(
    buildApiUrl(`/api/projects/${projectId}/permissions`),
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(update),
    },
  )
  if (!res.ok) throw new Error(`Failed to update permission for ${projectId}`)
  return res.json()
}

export async function createProjectPermission(
  payload: ProjectPermissionCreate,
): Promise<ProjectPermission> {
  const res = await fetchApi(buildApiUrl('/api/projects/permissions'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok)
    throw new Error(`Failed to create permission for ${payload.project_id}`)
  return res.json()
}

export async function deleteProjectPermission(
  projectId: string,
): Promise<void> {
  const res = await fetchApi(
    buildApiUrl(`/api/projects/${projectId}/permissions`),
    {
      method: 'DELETE',
    },
  )
  if (!res.ok) throw new Error(`Failed to delete permission for ${projectId}`)
}

export async function fetchExecutionPermission(
  projectId: string,
): Promise<ExecutionPermission> {
  const res = await fetchApi(
    buildApiUrl(`/api/projects/${projectId}/execution-permission`),
  )
  if (!res.ok)
    throw new Error(`Failed to fetch execution permission for ${projectId}`)
  return res.json()
}
