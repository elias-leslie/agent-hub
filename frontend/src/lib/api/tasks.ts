import { buildApiUrl, fetchApi } from '../api-config'

export interface TaskSearchItem {
  id: string
  project_id: string
  title: string
  description: string | null
  status: string
  priority: number | null
  task_type: string | null
}

export interface TaskSearchResponse {
  tasks: TaskSearchItem[]
  total: number
}

export async function searchTasks(params: {
  projectId: string
  query?: string
  status?: string | null
  limit?: number
}): Promise<TaskSearchResponse> {
  const search = new URLSearchParams()
  search.set('project_id', params.projectId)
  if (params.query) search.set('q', params.query)
  if (params.status !== null) search.set('status', params.status ?? 'pending')
  if (params.limit) search.set('limit', String(params.limit))

  const res = await fetchApi(
    buildApiUrl(`/api/tasks/search?${search.toString()}`),
  )
  if (!res.ok) {
    throw new Error(`Task search failed: ${res.status}`)
  }
  return res.json()
}
