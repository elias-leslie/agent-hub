import { fetchApi } from '@/lib/api-config'
import type { AgentPreview, PreviewTaskType } from '@/types/agent-preview'
import type { ContextUsage } from './sessions'

export type WorkflowStageName = 'clarify' | 'plan' | 'execute' | 'review' | 'qa'

export interface WorkflowStageRequest {
  task: string
  agent_slug?: string
  task_type?: string | null
  phase?: string | null
  use_memory?: boolean
  execute_tools?: boolean
  max_turns?: number
  working_dir?: string | null
  current_branch?: string | null
  thinking_level?: string | null
  disable_agent_fallbacks?: boolean
}

export interface WorkflowRequest {
  project_id: string
  parent_session_id?: string | null
  external_id?: string | null
  trace_id?: string | null
  shared_context?: string | null
  clarify?: WorkflowStageRequest | null
  plan?: WorkflowStageRequest | null
  execute?: WorkflowStageRequest | null
  review?: WorkflowStageRequest | null
  qa?: WorkflowStageRequest | null
}

export interface WorkflowUsage {
  input_tokens: number
  output_tokens: number
  total_tokens: number
}

export interface WorkflowStageResult {
  stage: WorkflowStageName
  agent_used: string | null
  content: string
  model: string
  provider: string
  session_id: string
  usage: WorkflowUsage
  context_usage: ContextUsage | null
  finish_reason?: string | null
  memory_facts_injected: number
  fallback_used: boolean
  fallback_reason?: string | null
  cited_uuids: string[]
}

export interface WorkflowResult {
  status: string
  stages: WorkflowStageResult[]
  final_output: string
  total_input_tokens: number
  total_output_tokens: number
}

export interface PersonaAutomation {
  id: string
  name: string
  schedule_type: 'at' | 'every' | 'cron'
  schedule_value: string
  schedule_timezone: string
  payload_type: 'agent_turn' | 'push' | 'self_honing'
  payload_message: string
  payload_title?: string | null
  delivery: 'none' | 'push'
  enabled: boolean
  last_run_at?: string | null
  next_run_at?: string | null
  run_count: number
  max_runs?: number | null
  created_at?: string | null
}

export interface PersonaAutomationTriggerResponse {
  job: PersonaAutomation
  output: string
  session_id?: string | null
  triggered_at: string
}

export interface PersonaAutomationCreateRequest {
  name: string
  schedule_type: 'at' | 'every' | 'cron'
  schedule_value: string
  schedule_timezone?: string
  payload_type?: 'agent_turn' | 'push' | 'self_honing'
  payload_message: string
  payload_title?: string | null
  delivery?: 'none' | 'push'
  enabled?: boolean
}

export interface PersonaAutomationUpdateRequest {
  name?: string
  schedule_type?: 'at' | 'every' | 'cron'
  schedule_value?: string
  schedule_timezone?: string
  payload_type?: 'agent_turn' | 'push' | 'self_honing'
  payload_message?: string
  payload_title?: string | null
  delivery?: 'none' | 'push'
  enabled?: boolean
}

export async function runPersonaWorkflow(
  request: WorkflowRequest,
): Promise<WorkflowResult> {
  const response = await fetchApi('/api/orchestration/workflow', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
  if (!response.ok) {
    throw new Error(`Workflow failed: ${response.status}`)
  }
  return response.json()
}

export async function fetchPersonaOperatorPreview(options: {
  projectId: string
  promptInput: string
  phase?: string
  taskType?: PreviewTaskType
}): Promise<AgentPreview> {
  const params = new URLSearchParams()
  params.set('project_id', options.projectId)
  params.set('prompt_input', options.promptInput)
  params.set('task_type', options.taskType ?? 'chat')
  if (options.phase) {
    params.set('phase', options.phase)
  }
  const response = await fetchApi(
    `/api/agents/persona/preview?${params.toString()}`,
  )
  if (!response.ok) {
    throw new Error(`Persona preview failed: ${response.status}`)
  }
  return response.json()
}

export async function fetchPersonaAutomations(): Promise<PersonaAutomation[]> {
  const response = await fetchApi('/api/persona/automations')
  if (!response.ok) {
    throw new Error(`Persona automations fetch failed: ${response.status}`)
  }
  return response.json()
}

export async function createPersonaAutomation(
  payload: PersonaAutomationCreateRequest,
): Promise<PersonaAutomation> {
  const response = await fetchApi('/api/persona/automations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(`Persona automation create failed: ${response.status}`)
  }
  return response.json()
}

export async function updatePersonaAutomation(
  jobId: string,
  payload: PersonaAutomationUpdateRequest,
): Promise<PersonaAutomation> {
  const response = await fetchApi(`/api/persona/automations/${jobId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(`Persona automation update failed: ${response.status}`)
  }
  return response.json()
}

export async function deletePersonaAutomation(jobId: string): Promise<void> {
  const response = await fetchApi(`/api/persona/automations/${jobId}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error(`Persona automation delete failed: ${response.status}`)
  }
}

export async function triggerPersonaAutomation(
  jobId: string,
): Promise<PersonaAutomationTriggerResponse> {
  const response = await fetchApi(`/api/persona/automations/${jobId}/trigger`, {
    method: 'POST',
  })
  if (!response.ok) {
    throw new Error(`Persona automation trigger failed: ${response.status}`)
  }
  return response.json()
}
