export type PreviewTaskType = 'chat' | 'heartbeat' | 'wake' | 'review'

export interface AgentPreviewSection {
  label: string
  source_kind: string
  source_id: string
  placement: string
  role?: string | null
  priority?: number | null
  updated_at?: string | null
  content_hash: string
  chars: number
  estimated_tokens: number
  content: string
}

export interface AgentPreviewMemoryPlanEntry {
  uuid: string
  block: string
  tier: string
  reason: string
  summary?: string | null
  full_tokens?: number | null
  rendered_tokens?: number | null
}

export interface AgentPreviewMemoryDebug {
  mandates_count?: number
  guardrails_count?: number
  reference_count?: number
  total_tokens?: number
  query?: string
  task_type?: string | null
  phase?: string | null
  tier_counts?: Record<string, number>
  render_chars?: number
  full_chars?: number
  render_chars_saved?: number
  memory_plan?: AgentPreviewMemoryPlanEntry[]
  [key: string]: unknown
}

export interface AgentPreview {
  slug: string
  name: string
  combined_prompt: string
  full_context: string
  memory_query: string
  memory_debug: AgentPreviewMemoryDebug
  loaded_memory_uuids: string[]
  reference_uuids: string[]
  mandate_count: number
  guardrail_count: number
  mandate_uuids: string[]
  guardrail_uuids: string[]
  task_type?: PreviewTaskType | null
  phase?: string | null
  project_id?: string | null
  task_prompt?: string | null
  sections: AgentPreviewSection[]
}

export interface PreviewScenario {
  projectId: string
  phase: string
  promptInput: string
}

export interface PreviewProjectOption {
  id: string
  name: string
  rootPath?: string | null
}

export const DEFAULT_PREVIEW_SCENARIO: PreviewScenario = {
  projectId: 'agent-hub',
  phase: '',
  promptInput: '',
}
