import { fetchProjectPermissions, fetchProjectRoots } from '@/lib/api'

export interface ProjectConfig {
  id: string
  name: string
  rootPath: string | null
}

function formatProjectName(projectId: string): string {
  return projectId
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export async function fetchProjectConfigs(): Promise<ProjectConfig[]> {
  const [permissions, canonicalRoots] = await Promise.all([
    fetchProjectPermissions(),
    fetchProjectRoots(),
  ])
  return permissions
    .map((permission) => ({
      id: permission.project_id,
      name: formatProjectName(permission.project_id),
      rootPath: canonicalRoots[permission.project_id] ?? permission.root_path,
    }))
    .sort((a, b) => a.name.localeCompare(b.name))
}
