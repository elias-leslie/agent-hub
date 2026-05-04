import type { PersonaStreamEventPreview } from '@/lib/api/persona-stream'
import type { SessionEvent as LiveSessionEvent } from '@/types/events'
import type { FilterMode } from './pulse-helpers'
import type { ItemTimelineBlock } from './workspace-types'
import { heartbeatIsImportant, shortenText } from './workspace-utils'

export function mergeEventPreviews(
  original: PersonaStreamEventPreview[],
  live: PersonaStreamEventPreview[],
): PersonaStreamEventPreview[] {
  if (live.length === 0) return original
  const deduped = new Map<string, PersonaStreamEventPreview>()
  for (const preview of [...live, ...original]) {
    if (!deduped.has(preview.id)) deduped.set(preview.id, preview)
  }
  return Array.from(deduped.values()).slice(0, 12)
}

function safeStringField(data: unknown, field: string): string | null {
  if (typeof data !== 'object' || data === null || !(field in data)) return null
  const val = (data as Record<string, unknown>)[field]
  return typeof val === 'string' ? val : null
}

function safeObjectField(
  data: unknown,
  field: string,
): Record<string, unknown> | null {
  if (typeof data !== 'object' || data === null || !(field in data)) return null
  const val = (data as Record<string, unknown>)[field]
  return typeof val === 'object' && val !== null
    ? (val as Record<string, unknown>)
    : null
}

function safeBoolField(data: unknown, field: string): boolean | null {
  if (typeof data !== 'object' || data === null || !(field in data)) return null
  const val = (data as Record<string, unknown>)[field]
  return typeof val === 'boolean' ? val : null
}

function safeNumberField(data: unknown, field: string): number | null {
  if (typeof data !== 'object' || data === null || !(field in data)) return null
  const val = (data as Record<string, unknown>)[field]
  return typeof val === 'number' ? val : null
}

export function buildLivePreview(
  event: LiveSessionEvent,
): PersonaStreamEventPreview | null {
  const previewId = `live:${event.session_id}:${event.timestamp}:${event.event_type}`

  if (event.event_type === 'message') {
    return {
      id: previewId,
      event_type: safeStringField(event.data, 'role')
        ? `${safeStringField(event.data, 'role')}_message`
        : 'assistant_message',
      created_at: event.timestamp,
      role: safeStringField(event.data, 'role'),
      tool_name: null,
      content_preview: safeStringField(event.data, 'content'),
      tool_input_preview: null,
      tool_output_preview: null,
      duration_ms: null,
      model_used: null,
    }
  }
  if (event.event_type === 'tool_use') {
    return {
      id: previewId,
      event_type: 'tool_use',
      created_at: event.timestamp,
      role: null,
      tool_name: safeStringField(event.data, 'tool_name'),
      content_preview: null,
      tool_input_preview: safeObjectField(event.data, 'tool_input')
        ? JSON.stringify(safeObjectField(event.data, 'tool_input'))
        : null,
      tool_output_preview: safeObjectField(event.data, 'tool_output')
        ? JSON.stringify(safeObjectField(event.data, 'tool_output'))
        : null,
      duration_ms: null,
      model_used: null,
    }
  }
  if (event.event_type === 'tool_result') {
    const toolOutput = safeObjectField(event.data, 'tool_output')
    return {
      id: previewId,
      event_type: 'tool_result',
      created_at: event.timestamp,
      role: null,
      tool_name: safeStringField(event.data, 'tool_name'),
      content_preview: toolOutput
        ? safeStringField(toolOutput, 'content')
        : null,
      tool_input_preview: null,
      tool_output_preview: toolOutput ? JSON.stringify(toolOutput) : null,
      duration_ms: safeNumberField(event.data, 'duration_ms'),
      model_used: null,
    }
  }
  if (event.event_type === 'error') {
    return {
      id: previewId,
      event_type: 'error',
      created_at: event.timestamp,
      role: null,
      tool_name: null,
      content_preview:
        safeStringField(event.data, 'error_message') || 'Session error',
      tool_input_preview: null,
      tool_output_preview: null,
      duration_ms: null,
      model_used: null,
    }
  }
  if (event.event_type === 'complete') {
    return {
      id: previewId,
      event_type: 'tool_result',
      created_at: event.timestamp,
      role: null,
      tool_name: null,
      content_preview: 'Execution completed',
      tool_input_preview: null,
      tool_output_preview: null,
      duration_ms: null,
      model_used: null,
    }
  }
  return null
}

export function liveSummaryFromEvent(event: LiveSessionEvent): string | null {
  if (event.event_type === 'tool_use') {
    const toolName = safeStringField(event.data, 'tool_name') || 'tool'
    return `Running ${toolName}`
  }
  if (event.event_type === 'tool_result') {
    const toolName = safeStringField(event.data, 'tool_name') || 'tool'
    const toolOutput = safeObjectField(event.data, 'tool_output')
    const content = toolOutput ? safeStringField(toolOutput, 'content') : null
    const isError =
      safeBoolField(event.data, 'is_error') ??
      (toolOutput ? safeBoolField(toolOutput, 'is_error') : false) ??
      false
    if (isError) return `Tool failed: ${toolName}`
    return content
      ? shortenText(content, 96)
      : `Waiting for model after ${toolName}`
  }
  if (event.event_type === 'message') {
    const content = safeStringField(event.data, 'content')
    return content ? shortenText(content, 96) : 'New message'
  }
  if (event.event_type === 'error') {
    const errorMessage =
      safeStringField(event.data, 'error_message') || 'Session error'
    return `Error: ${shortenText(errorMessage, 88)}`
  }
  if (event.event_type === 'complete') return 'Execution completed'
  if (event.event_type === 'session_start') return 'Session started'
  return null
}

export function liveStatusFromEvent(event: LiveSessionEvent): string | null {
  if (event.event_type === 'complete') return 'completed'
  if (event.event_type === 'error') return 'failed'
  if (event.event_type === 'tool_result') {
    const toolOutput = safeObjectField(event.data, 'tool_output')
    const isError =
      safeBoolField(event.data, 'is_error') ??
      (toolOutput ? safeBoolField(toolOutput, 'is_error') : false) ??
      false
    return isError ? 'failed' : 'active'
  }
  return 'active'
}

export function isRoutineHeartbeatBlock(
  block: ItemTimelineBlock,
  searchActive: boolean,
  filterMode: FilterMode,
): boolean {
  if (searchActive || filterMode !== 'all') return false
  if (block.anchorItem.kind !== 'heartbeat') return false
  if (block.childRuns.length > 0) return false
  const entry = block.anchorItem.entry
  if (entry.status !== 'completed' || entry.live_status === 'active')
    return false
  if (entry.event_previews.some((preview) => preview.event_type === 'error'))
    return false
  if (entry.event_previews.length > 4) return false
  if (heartbeatIsImportant(entry)) return false
  const summary =
    `${entry.display_summary ?? ''} ${entry.summary_oneliner ?? ''} ${entry.live_summary ?? ''}`.toLowerCase()
  if (summary.trim().length > 140) return false
  return (
    (entry.tool_count <= 2 && entry.message_count <= 0) ||
    summary.includes('waiting for model') ||
    summary.includes('execution completed')
  )
}
