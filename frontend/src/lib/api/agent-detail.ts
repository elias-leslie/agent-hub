import type {
  Agent,
  AgentPreview,
  ModelInfo,
  PreviewTaskType,
} from '@/app/agents/[slug]/types'
import { fetchApi } from '@/lib/api-config'

export async function fetchAgent(slug: string): Promise<Agent> {
  const res = await fetchApi(`/api/agents/${slug}`)
  if (!res.ok) throw new Error('Failed to fetch agent')
  return res.json()
}

export async function updateAgent(
  slug: string,
  data: Partial<Agent>,
): Promise<Agent> {
  const res = await fetchApi(`/api/agents/${slug}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update agent')
  return res.json()
}

export interface PreviewRequestOptions {
  taskType?: PreviewTaskType
  projectId?: string
  phase?: string
  promptInput?: string
}

export async function fetchPreview(
  slug: string,
  options: PreviewRequestOptions = {},
): Promise<AgentPreview> {
  const params = new URLSearchParams()
  if (options.taskType) params.set('task_type', options.taskType)
  if (options.projectId) params.set('project_id', options.projectId)
  if (options.phase) params.set('phase', options.phase)
  if (options.promptInput) params.set('prompt_input', options.promptInput)
  const query = params.toString()
  const res = await fetchApi(
    `/api/agents/${slug}/preview${query ? `?${query}` : ''}`,
  )
  if (!res.ok) throw new Error('Failed to fetch preview')
  return res.json()
}

export async function fetchModels(): Promise<ModelInfo[]> {
  const { getModels } = await import('@/lib/models')
  try {
    return await getModels()
  } catch {
    return []
  }
}
