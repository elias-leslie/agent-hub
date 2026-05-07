import type {
  Agent,
  AgentPreview,
  AgentRouting,
  AgentRoutingUpdate,
  ModelInfo,
  PreviewTaskType,
  WorkloadRoutingUpdate,
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

export async function fetchAgentRouting(slug: string): Promise<AgentRouting> {
  const res = await fetchApi(`/api/agents/${slug}/routing`)
  if (!res.ok) throw new Error('Failed to fetch agent routing')
  return res.json()
}

export async function updateAgentRouting(
  slug: string,
  data: AgentRoutingUpdate,
): Promise<AgentRouting> {
  const res = await fetchApi(`/api/agents/${slug}/routing`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update agent routing')
  return res.json()
}

export async function updateAgentWorkloadRouting(
  slug: string,
  workloadProfile: string,
  data: WorkloadRoutingUpdate,
): Promise<AgentRouting> {
  const res = await fetchApi(
    `/api/agents/${slug}/routing/workloads/${encodeURIComponent(workloadProfile)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    },
  )
  if (!res.ok) throw new Error('Failed to update workload routing')
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
