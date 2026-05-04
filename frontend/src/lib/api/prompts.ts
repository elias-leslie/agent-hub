import { fetchApi } from '@/lib/api-config'

export const PLATFORM_CONTEXT_PROMPT_SLUG = 'platform-context'

export interface Prompt {
  id: number
  slug: string
  name: string
  content: string
  description: string | null
  is_global: boolean
  enabled: boolean
  exclude_agents: string[]
  owner_agent_slug: string | null
  prompt_type: string
  deletion_locked: boolean
  created_at: string
  updated_at: string
}

export interface PromptRevision {
  id: string
  prompt_id: number | null
  prompt_slug: string
  prompt_name: string
  action: string
  content: string
  description: string | null
  is_global: boolean
  enabled: boolean
  exclude_agents: string[]
  owner_agent_id: number | null
  prompt_type: string
  deletion_locked: boolean
  content_hash: string
  changed_by: string | null
  change_reason: string | null
  created_at: string
}

export interface PromptListResponse {
  prompts: Prompt[]
  total: number
}

export interface PromptRevisionListResponse {
  revisions: PromptRevision[]
  total: number
}

export interface AgentPromptAssignment {
  prompt: Prompt
  role: string
  priority: number
}

export async function fetchPrompts(isGlobal?: boolean): Promise<Prompt[]> {
  const params = new URLSearchParams()
  if (isGlobal !== undefined) params.set('is_global', String(isGlobal))
  const qs = params.toString()
  const res = await fetchApi(`/api/prompts${qs ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error('Failed to fetch prompts')
  const data: PromptListResponse = await res.json()
  return data.prompts
}

export async function fetchPrompt(slug: string): Promise<Prompt> {
  const res = await fetchApi(`/api/prompts/${slug}`)
  if (!res.ok) throw new Error('Failed to fetch prompt')
  return res.json()
}

export async function fetchOptionalPrompt(
  slug: string,
): Promise<Prompt | null> {
  const res = await fetchApi(`/api/prompts/${slug}`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error('Failed to fetch prompt')
  return res.json()
}

export async function createPrompt(data: {
  slug: string
  name: string
  content: string
  description?: string
  is_global?: boolean
  enabled?: boolean
  exclude_agents?: string[]
}): Promise<Prompt> {
  const res = await fetchApi('/api/prompts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to create prompt')
  return res.json()
}

export async function updatePrompt(
  slug: string,
  data: Partial<Omit<Prompt, 'id' | 'created_at' | 'updated_at'>> & {
    change_reason?: string
  },
): Promise<Prompt> {
  const res = await fetchApi(`/api/prompts/${slug}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update prompt')
  return res.json()
}

export async function fetchPromptRevisions(
  slug: string,
  limit = 20,
): Promise<PromptRevision[]> {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  const res = await fetchApi(`/api/prompts/${slug}/revisions?${params}`)
  if (!res.ok) throw new Error('Failed to fetch prompt revisions')
  const data: PromptRevisionListResponse = await res.json()
  return data.revisions
}

export async function restorePromptRevision(
  slug: string,
  revisionId: string,
  changeReason?: string,
): Promise<Prompt> {
  const res = await fetchApi(
    `/api/prompts/${slug}/revisions/${revisionId}/restore`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ change_reason: changeReason }),
    },
  )
  if (!res.ok) throw new Error('Failed to restore prompt revision')
  return res.json()
}

export async function deletePrompt(slug: string): Promise<void> {
  const res = await fetchApi(`/api/prompts/${slug}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete prompt')
}

export async function fetchAgentPrompts(
  agentSlug: string,
): Promise<AgentPromptAssignment[]> {
  const res = await fetchApi(`/api/prompts/agents/${agentSlug}/assignments`)
  if (!res.ok) throw new Error('Failed to fetch agent prompts')
  const data = await res.json()
  return data.assignments
}

export async function assignPrompt(
  agentSlug: string,
  data: { prompt_slug: string; role: string; priority?: number },
): Promise<AgentPromptAssignment> {
  const res = await fetchApi(`/api/prompts/agents/${agentSlug}/assignments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to assign prompt')
  return res.json()
}

export async function updateAssignment(
  agentSlug: string,
  promptSlug: string,
  data: { role?: string; priority?: number },
): Promise<AgentPromptAssignment> {
  const res = await fetchApi(
    `/api/prompts/agents/${agentSlug}/assignments/${promptSlug}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    },
  )
  if (!res.ok) throw new Error('Failed to update assignment')
  return res.json()
}

export async function removeAssignment(
  agentSlug: string,
  promptSlug: string,
): Promise<void> {
  const res = await fetchApi(
    `/api/prompts/agents/${agentSlug}/assignments/${promptSlug}`,
    { method: 'DELETE' },
  )
  if (!res.ok) throw new Error('Failed to remove assignment')
}
