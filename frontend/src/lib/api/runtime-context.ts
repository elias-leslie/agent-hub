import { fetchApi } from '@/lib/api-config'

export type RuntimeSourceType = 'prompt' | 'memory'
export type RuntimeOverrideMode = 'include' | 'exclude' | 'order'
export type RuntimeTierOverride = 'L0' | 'L1' | 'L2'

export interface RuntimeContextProfile {
  consumer_profile: string
  label: string
}

export interface RuntimeContextOverridePayload {
  source_type: RuntimeSourceType
  source_id: string
  mode: RuntimeOverrideMode
  position: number
  enabled: boolean
  note?: string | null
  tier_override?: RuntimeTierOverride | null
}

export interface RuntimeContextOverride extends RuntimeContextOverridePayload {
  id: string
  consumer_profile: string
  project_id: string | null
}

export interface RuntimeContextBlock {
  id: string
  source_type: RuntimeSourceType
  source_id: string
  title: string
  content: string
  token_count: number
  origin: 'auto' | 'override'
  mode: RuntimeOverrideMode
  position: number
  tier: string | null
  // Effective L0/L1/L2 render tier (null for prompt blocks).
  render_tier?: string | null
  // Per-memory render-mode preference (full | compact | summary | null).
  render_mode?: 'full' | 'compact' | 'summary' | null
  // Resolved per-profile/per-project tier override, if any.
  tier_override?: RuntimeTierOverride | null
}

export interface RuntimeContextPreview {
  consumer_profile: string
  project_id: string | null
  query: string
  total_tokens: number
  rendered: string
  blocks: RuntimeContextBlock[]
  overrides: RuntimeContextOverride[]
}

export async function fetchRuntimeProfiles(): Promise<RuntimeContextProfile[]> {
  const res = await fetchApi('/api/runtime-context/profiles')
  if (!res.ok) throw new Error('Failed to fetch runtime profiles')
  const data: { profiles: RuntimeContextProfile[] } = await res.json()
  return data.profiles
}

export async function fetchRuntimeOverrides(params: {
  consumerProfile: string
  projectId?: string
}): Promise<RuntimeContextOverride[]> {
  const query = new URLSearchParams()
  if (params.projectId) query.set('project_id', params.projectId)
  const qs = query.toString()
  const res = await fetchApi(
    `/api/runtime-context/${params.consumerProfile}/overrides${qs ? `?${qs}` : ''}`,
  )
  if (!res.ok) throw new Error('Failed to fetch runtime overrides')
  const data: { overrides: RuntimeContextOverride[] } = await res.json()
  return data.overrides
}

export async function replaceRuntimeOverrides(params: {
  consumerProfile: string
  projectId?: string
  overrides: RuntimeContextOverridePayload[]
}): Promise<RuntimeContextOverride[]> {
  const query = new URLSearchParams()
  if (params.projectId) query.set('project_id', params.projectId)
  const qs = query.toString()
  const res = await fetchApi(
    `/api/runtime-context/${params.consumerProfile}/overrides${qs ? `?${qs}` : ''}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ overrides: params.overrides }),
    },
  )
  if (!res.ok) throw new Error('Failed to save runtime overrides')
  const data: { overrides: RuntimeContextOverride[] } = await res.json()
  return data.overrides
}

export async function fetchRuntimePreview(params: {
  consumerProfile: string
  projectId?: string
  query?: string
  taskType?: string
  phase?: string
  includeGlobal?: boolean
}): Promise<RuntimeContextPreview> {
  const query = new URLSearchParams()
  if (params.projectId) query.set('project_id', params.projectId)
  if (params.query) query.set('query', params.query)
  if (params.taskType) query.set('task_type', params.taskType)
  if (params.phase) query.set('phase', params.phase)
  if (params.includeGlobal !== undefined) {
    query.set('include_global', String(params.includeGlobal))
  }
  const qs = query.toString()
  const res = await fetchApi(
    `/api/runtime-context/${params.consumerProfile}/preview${qs ? `?${qs}` : ''}`,
  )
  if (!res.ok) throw new Error('Failed to fetch runtime preview')
  return res.json()
}
