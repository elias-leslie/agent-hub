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
