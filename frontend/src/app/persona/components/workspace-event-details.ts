import type { PersonaIssueMarker } from '@/lib/api/persona-stream'
import type { TimelineEvent } from '@/types/events'
import type { DetailField, SessionDetailBlock } from './workspace-types'
import {
  addUniqueText,
  compactPath,
  eventSummaryLabel,
  formatDurationLabel,
  humanizeFieldLabel,
  isGenericStatusText,
  isPromptLikeText,
  isRecord,
  normalizeText,
  prettifyDisplayText,
} from './workspace-utils'

export function describeValue(value: unknown): string | null {
  if (value == null) return null
  if (typeof value === 'string') {
    const p = prettifyDisplayText(value)
    return p || null
  }
  if (typeof value === 'number' || typeof value === 'boolean')
    return String(value)
  if (Array.isArray(value)) {
    const items = value
      .map((item) => describeValue(item))
      .filter((item): item is string => Boolean(item))
    return items.length > 0 ? items.join(', ') : null
  }
  return null
}

function fieldTone(label: string, value: string): DetailField['tone'] {
  const normalizedValue = value.toLowerCase()
  const normalizedLabel = label.toLowerCase()
  if (normalizedLabel.includes('status')) {
    if (['ok', 'success', 'succeeded', 'completed'].includes(normalizedValue))
      return 'success'
    if (['failed', 'error', 'blocked'].includes(normalizedValue))
      return 'danger'
  }
  if (normalizedLabel.includes('exit code'))
    return normalizedValue === '0' ? 'success' : 'danger'
  if (normalizedValue === 'true' && normalizedLabel.includes('error'))
    return 'danger'
  if (normalizedLabel.includes('file') || normalizedLabel.includes('path'))
    return 'info'
  if (normalizedLabel.includes('task')) return 'warning'
  return 'neutral'
}

function flattenReadableFields(
  value: unknown,
  parentKey = '',
  depth = 0,
): DetailField[] {
  if (depth > 3 || value == null) return []
  if (Array.isArray(value)) {
    if (value.every((item) => !isRecord(item) && !Array.isArray(item))) {
      const described = describeValue(value)
      return described && parentKey
        ? [{ label: humanizeFieldLabel(parentKey), value: described }]
        : []
    }
    return value.flatMap((item, index) =>
      flattenReadableFields(
        item,
        parentKey ? `${parentKey}.${index + 1}` : String(index + 1),
        depth + 1,
      ),
    )
  }
  if (!isRecord(value)) {
    const described = describeValue(value)
    return described && parentKey
      ? [{ label: humanizeFieldLabel(parentKey), value: described }]
      : []
  }

  const preferredOrder = [
    'command',
    'action',
    'description',
    'path',
    'file_path',
    'target_file',
    'task_id',
    'project',
    'project_id',
    'status',
    'exit_code',
    'current_branch',
    'branch',
    'files_touched',
    'changed_files',
  ]
  const entries = Object.entries(value).sort(([left], [right]) => {
    const leftIndex = preferredOrder.indexOf(left)
    const rightIndex = preferredOrder.indexOf(right)
    if (leftIndex === -1 && rightIndex === -1) return left.localeCompare(right)
    if (leftIndex === -1) return 1
    if (rightIndex === -1) return -1
    return leftIndex - rightIndex
  })
  return entries.flatMap(([key, nestedValue]) =>
    flattenReadableFields(
      nestedValue,
      parentKey ? `${parentKey}.${key}` : key,
      depth + 1,
    ),
  )
}

export function buildEventDetails(event: TimelineEvent): {
  lead: string | null
  textBlocks: string[]
  fields: DetailField[]
} {
  const textBlocks: string[] = []
  const textSeen = new Set<string>()
  const fields: DetailField[] = []
  const fieldSeen = new Set<string>()

  const addField = (
    label: string,
    value: string | null | undefined,
    tone?: DetailField['tone'],
  ) => {
    if (!value) return
    const trimmed = value.trim()
    if (!trimmed) return
    const fieldKey = `${label}:${normalizeText(trimmed)}`
    if (fieldSeen.has(fieldKey)) return
    fieldSeen.add(fieldKey)
    fields.push({
      label,
      value: trimmed,
      tone: tone ?? fieldTone(label, trimmed),
    })
  }

  const recordTextFields = (
    value: Record<string, unknown> | null,
    keys: string[],
  ) => {
    if (!value) return
    for (const key of keys)
      addUniqueText(textBlocks, textSeen, describeValue(value[key]))
  }

  const filterFields = (
    source: Record<string, unknown> | null,
    excludedKeys: string[],
  ) => {
    if (!source) return
    const exclusions = new Set(excludedKeys)
    for (const field of flattenReadableFields(source)) {
      const normalizedLabel = field.label.toLowerCase().replaceAll(' ', '_')
      if ([...exclusions].some((key) => normalizedLabel.endsWith(key))) continue
      const value =
        field.label.toLowerCase().includes('file') ||
        field.label.toLowerCase().includes('path')
          ? compactPath(field.value)
          : field.value
      addField(field.label, value, field.tone)
    }
  }

  if (event.event_type === 'tool_use') {
    const toolInput = isRecord(event.tool_input) ? event.tool_input : null
    addField('Command', describeValue(toolInput?.command), 'info')
    addField('Action', describeValue(toolInput?.action))
    addField('Description', describeValue(toolInput?.description))
    addField(
      'File',
      describeValue(
        toolInput?.file_path ?? toolInput?.path ?? toolInput?.target_file,
      ),
      'info',
    )
    addField('Task', describeValue(toolInput?.task_id), 'warning')
    addField(
      'Project',
      describeValue(toolInput?.project ?? toolInput?.project_id),
    )
    filterFields(toolInput, [
      'command',
      'action',
      'description',
      'file_path',
      'path',
      'target_file',
      'task_id',
      'project',
      'project_id',
    ])
  } else if (event.event_type === 'tool_result') {
    const toolOutput = isRecord(event.tool_output) ? event.tool_output : null
    recordTextFields(toolOutput, [
      'content',
      'summary',
      'stdout',
      'stderr',
      'error_message',
      'message',
    ])
    addField('Status', describeValue(toolOutput?.status))
    addField('Exit code', describeValue(toolOutput?.exit_code))
    addField('Error', describeValue(toolOutput?.is_error))
    addField('Task', describeValue(toolOutput?.task_id), 'warning')
    addField(
      'File',
      describeValue(
        toolOutput?.file_path ?? toolOutput?.path ?? toolOutput?.target_file,
      ),
      'info',
    )
    addField(
      'Files touched',
      describeValue(toolOutput?.files_touched ?? toolOutput?.changed_files),
      'info',
    )
    filterFields(toolOutput, [
      'content',
      'summary',
      'stdout',
      'stderr',
      'error_message',
      'message',
      'status',
      'exit_code',
      'is_error',
      'task_id',
      'file_path',
      'path',
      'target_file',
      'files_touched',
      'changed_files',
    ])
  } else {
    addUniqueText(textBlocks, textSeen, event.content)
  }

  if (event.duration_ms != null)
    addField('Duration', formatDurationLabel(event.duration_ms))
  if (event.model_used) addField('Model', event.model_used)

  const lead = textBlocks[0] ?? fields[0]?.value ?? null
  return { lead, textBlocks, fields }
}

export function dedupeDetailFields(fields: DetailField[]): DetailField[] {
  const seen = new Set<string>()
  return fields.filter((field) => {
    const key = `${field.label}:${normalizeText(field.value)}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function dedupeTextBlocks(values: string[]): string[] {
  const deduped: string[] = []
  const seen = new Set<string>()
  for (const value of values) addUniqueText(deduped, seen, value)
  return deduped
}

export function eventImportanceScore(
  event: TimelineEvent,
  details: ReturnType<typeof buildEventDetails>,
): number {
  const combinedText = [details.lead, ...details.textBlocks]
    .join(' ')
    .toLowerCase()
  const fieldText = details.fields
    .map((field) => `${field.label} ${field.value}`)
    .join(' ')
    .toLowerCase()

  if (event.event_type === 'error') return 100
  if (
    event.event_type === 'memory_inject' ||
    event.event_type === 'memory_cite'
  )
    return 0
  if (
    (event.event_type === 'system_message' || event.role === 'system') &&
    isPromptLikeText(event.content)
  )
    return 0
  if (event.event_type === 'thinking')
    return combinedText.includes('error') || combinedText.includes('blocked')
      ? 40
      : 5
  if (event.event_type === 'tool_result') {
    const hasFailureSignal =
      combinedText.includes('error') ||
      combinedText.includes('failed') ||
      fieldText.includes('exit code 1') ||
      fieldText.includes('status failed') ||
      fieldText.includes('error true')
    if (hasFailureSignal) return 95
    const hasStrongOutcome =
      combinedText.includes('publish') ||
      combinedText.includes('commit') ||
      combinedText.includes('verified') ||
      combinedText.includes('merged') ||
      combinedText.includes('completed') ||
      combinedText.includes('passed') ||
      fieldText.includes('task') ||
      fieldText.includes('files touched')
    if (hasStrongOutcome) return 82
    return isGenericStatusText(details.lead) ? 20 : 55
  }
  if (event.event_type === 'tool_use') {
    const hasActionSignal =
      combinedText.includes('publish') ||
      combinedText.includes('commit') ||
      combinedText.includes('verify') ||
      combinedText.includes('dispatch') ||
      fieldText.includes('task') ||
      fieldText.includes('file')
    return hasActionSignal ? 58 : 25
  }
  if (
    event.event_type === 'assistant_message' ||
    event.event_type === 'user_message'
  ) {
    if (isPromptLikeText(event.content)) return 0
    return isGenericStatusText(details.lead) ? 20 : 72
  }
  return isGenericStatusText(details.lead) ? 18 : 48
}

export function buildSessionDetailBlocks(
  events: TimelineEvent[],
): SessionDetailBlock[] {
  const blocks: SessionDetailBlock[] = []
  for (let index = 0; index < events.length; index += 1) {
    const event = events[index]
    const nextEvent = events[index + 1]

    if (
      event.event_type === 'tool_use' &&
      nextEvent?.event_type === 'tool_result' &&
      nextEvent.turn === event.turn &&
      nextEvent.tool_name === event.tool_name
    ) {
      const useDetails = buildEventDetails(event)
      const resultDetails = buildEventDetails(nextEvent)
      const mergedText = dedupeTextBlocks(
        [
          resultDetails.lead,
          useDetails.lead,
          ...resultDetails.textBlocks,
          ...useDetails.textBlocks,
        ].filter((v): v is string => Boolean(v)),
      )
      const mergedFields = dedupeDetailFields([
        ...useDetails.fields,
        ...resultDetails.fields,
      ])
      const mergedLead =
        mergedText[0] ?? resultDetails.lead ?? useDetails.lead ?? null
      const resultScore = eventImportanceScore(nextEvent, resultDetails)

      blocks.push({
        id: `${event.id}:${nextEvent.id}`,
        timestamp: nextEvent.created_at,
        eventType: nextEvent.event_type,
        label: event.tool_name || 'Tool',
        title: event.tool_name ? `${event.tool_name}` : 'Tool activity',
        lead: mergedLead,
        textBlocks: mergedLead ? mergedText.slice(1) : mergedText,
        fields: mergedFields,
        score: Math.max(resultScore, 48),
        defaultVisible: resultScore >= 60,
      })
      index += 1
      continue
    }

    const details = buildEventDetails(event)
    const score = eventImportanceScore(event, details)
    blocks.push({
      id: event.id,
      timestamp: event.created_at,
      eventType: event.event_type,
      label: event.tool_name || eventSummaryLabel(event.event_type),
      title: event.tool_name || eventSummaryLabel(event.event_type),
      lead: details.lead,
      textBlocks: details.lead
        ? details.textBlocks.slice(1)
        : details.textBlocks,
      fields: details.fields,
      score,
      defaultVisible: score >= 60,
    })
  }
  return blocks
}

export function blockMatchesIssueMarker(
  block: SessionDetailBlock,
  marker: PersonaIssueMarker,
): boolean {
  if (
    block.id === marker.event_id ||
    block.id.split(':').includes(marker.event_id)
  )
    return true
  const haystack =
    `${block.title ?? ''} ${block.lead ?? ''} ${block.textBlocks.join(' ')}`.toLowerCase()
  if (marker.tool_name && haystack.includes(marker.tool_name.toLowerCase()))
    return true
  const markerWords = `${marker.title} ${marker.summary} ${marker.detail ?? ''}`
    .toLowerCase()
    .split(/\s+/)
    .filter((token) => token.length > 4)
  return markerWords.some((token) => haystack.includes(token))
}

export function buildIssueDetailBlocks(
  blocks: SessionDetailBlock[],
  markers: PersonaIssueMarker[],
): SessionDetailBlock[] {
  const selected: SessionDetailBlock[] = []
  const seen = new Set<string>()
  for (const marker of markers) {
    const match = blocks.find((block) => blockMatchesIssueMarker(block, marker))
    if (match && !seen.has(match.id)) {
      seen.add(match.id)
      selected.push(match)
    }
  }
  return selected
}
