import { buildApiUrl, fetchApi } from '../api-config'

export interface WorkChatBinding {
  id: string
  session_id: string
  surface: string
  pane_id: string | null
  project_id: string | null
  task_id: string | null
  feedback_id: string | null
  design_id: string | null
  telegram_chat_id: string | null
  telegram_thread_id: string | null
  telegram_message_id: string | null
  source_client: string | null
  work_context: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ActionRequest {
  id: string
  session_id: string
  status: string
  request_type: string
  prompt: string | null
  response_content: string | null
  telegram_chat_id: string | null
  telegram_thread_id: string | null
  telegram_message_id: string | null
  correlation_id: string | null
  join_code: string | null
  source_client: string | null
  metadata: Record<string, unknown>
  created_at: string
  resolved_at: string | null
  expires_at: string | null
}

export async function upsertWorkChatBinding(
  binding: Partial<WorkChatBinding> & { session_id: string },
): Promise<WorkChatBinding> {
  const response = await fetchApi(buildApiUrl('/api/work-chats/bindings'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(binding),
  })
  if (!response.ok) {
    throw new Error(`Work chat binding failed: ${response.status}`)
  }
  return response.json()
}

export async function fetchWorkChatBindings(params?: {
  project_id?: string
  task_id?: string
  session_id?: string
  pane_id?: string
}): Promise<WorkChatBinding[]> {
  const search = new URLSearchParams()
  if (params?.project_id) search.set('project_id', params.project_id)
  if (params?.task_id) search.set('task_id', params.task_id)
  if (params?.session_id) search.set('session_id', params.session_id)
  if (params?.pane_id) search.set('pane_id', params.pane_id)
  const url = search.toString()
    ? `/api/work-chats/bindings?${search.toString()}`
    : '/api/work-chats/bindings'
  const response = await fetchApi(buildApiUrl(url))
  if (!response.ok) {
    throw new Error(`Work chat bindings fetch failed: ${response.status}`)
  }
  const data = await response.json()
  return data.bindings ?? []
}

export async function fetchActionRequests(params?: {
  session_id?: string
  status?: string
}): Promise<ActionRequest[]> {
  const search = new URLSearchParams()
  if (params?.session_id) search.set('session_id', params.session_id)
  if (params?.status) search.set('status', params.status)
  const url = search.toString()
    ? `/api/work-chats/action-requests?${search.toString()}`
    : '/api/work-chats/action-requests'
  const response = await fetchApi(buildApiUrl(url))
  if (!response.ok) {
    throw new Error(`Action requests fetch failed: ${response.status}`)
  }
  const data = await response.json()
  return data.action_requests ?? []
}
