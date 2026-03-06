import { fetchProjectPermissions } from "@/lib/api";

export interface ProjectConfig {
  id: string;
  name: string;
  rootPath: string | null;
}

function formatProjectName(projectId: string): string {
  return projectId
    .split(/[-_]/g)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export async function fetchProjectConfigs(): Promise<ProjectConfig[]> {
  const permissions = await fetchProjectPermissions();
  return permissions
    .map((permission) => ({
      id: permission.project_id,
      name: formatProjectName(permission.project_id),
      rootPath: permission.root_path,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}
