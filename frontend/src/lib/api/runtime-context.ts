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

export type RuntimeRenderMode = 'full' | 'compact' | 'summary'
export type RuntimeBlockSource = 'auto' | 'pinned'

export interface RuntimeContextBlock {
  id: string
  source_type: RuntimeSourceType
  source_id: string
  title: string
  content: string
  token_count: number
  origin: 'auto' | 'override'
  // Why this block is in (or excluded from) context.
  source: RuntimeBlockSource
  // Short tag explaining auto-injection (e.g. "tier:mandate", "global").
  auto_reason?: string | null
  mode: RuntimeOverrideMode
  position: number
  tier: string | null
  // DB prompt authority type; null for memory blocks.
  prompt_type?: string | null
  // Effective L0/L1/L2 render tier (null for prompt blocks).
  render_tier?: string | null
  // Per-memory render-mode preference (full | compact | summary | null).
  render_mode?: RuntimeRenderMode | null
  // Resolved per-profile/per-project tier override, if any.
  tier_override?: RuntimeTierOverride | null
  // "global" or "project" for memories; "global" / "agent" for prompts.
  scope?: string | null
  scope_id?: string | null
  // Free-form tags surfaced for filtering in the library.
  tags?: string[]
}

export interface RuntimeContextPreview {
  consumer_profile: string
  project_id: string | null
  query: string
  total_tokens: number
  budget_tokens: number
  budget_enabled: boolean
  rendered: string
  blocks: RuntimeContextBlock[]
  excluded: RuntimeContextBlock[]
  overrides: RuntimeContextOverride[]
  // Computed auxiliary blocks follow authority-ordered prompts/memory in the
  // canonical delivery and are surfaced for preview and inline rows.
  project_index?: string | null
  continuity?: string | null
  tool_capabilities?: string | null
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

export interface RuntimeContextProfilePolicy {
  consumer_profile: string
  // Null = uncapped. Integer = explicit cap.
  mandate_limit: number | null
  guardrail_limit: number | null
  reference_limit: number | null
}

export async function fetchRuntimePolicy(params: {
  consumerProfile: string
}): Promise<RuntimeContextProfilePolicy> {
  const res = await fetchApi(
    `/api/runtime-context/${params.consumerProfile}/policy`,
  )
  if (!res.ok) throw new Error('Failed to fetch runtime policy')
  return res.json()
}

export async function updateRuntimePolicy(params: {
  consumerProfile: string
  payload: {
    mandate_limit: number | null
    guardrail_limit: number | null
    reference_limit: number | null
  }
}): Promise<RuntimeContextProfilePolicy> {
  const res = await fetchApi(
    `/api/runtime-context/${params.consumerProfile}/policy`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params.payload),
    },
  )
  if (!res.ok) throw new Error('Failed to save runtime policy')
  return res.json()
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
