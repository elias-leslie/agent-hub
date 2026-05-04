import type {
  PersonaIssueMarker,
  PersonaStreamEntry,
} from '@/lib/api/persona-stream'

export type FilterMode =
  | 'all'
  | 'messages'
  | 'work'
  | 'heartbeats'
  | 'friction'
  | 'errors'
  | 'warnings'
  | 'stalled'
  | 'drift'
  | 'tool_friction'
  | 'retries'
  | 'recovered'
  | 'escalations'

const FILTER_TAG_MAP: Record<
  Exclude<FilterMode, 'all' | 'messages' | 'work' | 'heartbeats'>,
  string
> = {
  friction: 'friction',
  errors: 'error',
  warnings: 'warning',
  stalled: 'stalled',
  drift: 'instruction_drift',
  tool_friction: 'tool_friction',
  retries: 'retries',
  recovered: 'recovered',
  escalations: 'escalation',
}

export function filterModeToPulseTag(mode: FilterMode): string | null {
  if (mode in FILTER_TAG_MAP) {
    return FILTER_TAG_MAP[mode as keyof typeof FILTER_TAG_MAP]
  }
  return null
}

export function pulseTagToFilterMode(tag: string): FilterMode {
  switch (tag) {
    case 'friction':
      return 'friction'
    case 'error':
      return 'errors'
    case 'warning':
      return 'warnings'
    case 'stalled':
      return 'stalled'
    case 'instruction_drift':
      return 'drift'
    case 'tool_friction':
      return 'tool_friction'
    case 'retries':
      return 'retries'
    case 'recovered':
      return 'recovered'
    case 'escalation':
      return 'escalations'
    default:
      return 'all'
  }
}

export function pulseTagLabel(tag: string): string {
  switch (tag) {
    case 'friction':
      return 'Friction'
    case 'error':
      return 'Error'
    case 'warning':
      return 'Warning'
    case 'stalled':
      return 'Stalled'
    case 'retries':
      return 'Retries'
    case 'instruction_drift':
      return 'Instruction Drift'
    case 'tool_friction':
      return 'Tool Friction'
    case 'recovered':
      return 'Recovered'
    case 'escalation':
      return 'Escalation'
    default:
      return tag.replaceAll('_', ' ')
  }
}

export function rootCauseLabel(rootCause: string): string {
  switch (rootCause) {
    case 'workflow':
      return 'Workflow'
    case 'tool':
      return 'Tool'
    case 'context':
      return 'Context'
    case 'infra':
      return 'Infra'
    case 'prompt':
      return 'Prompt'
    default:
      return 'Unknown'
  }
}

export function pulseTagClasses(tag: string): string {
  switch (tag) {
    case 'friction':
      return 'bg-slate-200 text-slate-900'
    case 'error':
      return 'bg-rose-950/40 text-rose-300'
    case 'warning':
    case 'stalled':
    case 'escalation':
      return 'bg-amber-950/40 text-amber-300'
    case 'instruction_drift':
      return 'bg-fuchsia-950/40 text-fuchsia-300'
    case 'tool_friction':
    case 'retries':
      return 'bg-sky-950/40 text-sky-300'
    case 'recovered':
      return 'bg-emerald-950/40 text-emerald-300'
    default:
      return 'bg-slate-800 text-slate-300'
  }
}

export function entryHasPulseTag(
  entry: PersonaStreamEntry,
  tag: string,
): boolean {
  if (tag === 'friction') {
    return (
      entry.issue_markers.length > 0 || entry.pulse_tags.includes('friction')
    )
  }
  if (tag === 'recovered') {
    return entry.pulse_tags.includes('recovered')
  }
  if (entry.issue_markers.some((marker) => marker.tags.includes(tag))) {
    return true
  }
  return entry.pulse_tags.includes(tag)
}

export function issueMarkerHasPulseTag(
  marker: PersonaIssueMarker,
  tag: string,
): boolean {
  if (tag === 'friction') {
    return true
  }
  return marker.tags.includes(tag)
}

function normalizeIssueText(value: string | null | undefined): string {
  return (value ?? '').replace(/\s+/g, ' ').trim().toLowerCase()
}

function issueTaskId(marker: PersonaIssueMarker): string | null {
  const combined = `${marker.title}\n${marker.summary}\n${marker.detail ?? ''}`
  const match = combined.match(/\btask-[a-z0-9]+\b/i)
  return match ? match[0].toLowerCase() : null
}

function dedupeIssueMarkers(
  issueMarkers: PersonaIssueMarker[],
): PersonaIssueMarker[] {
  const preferred = [...issueMarkers].sort((left, right) => {
    if (
      left.event_type === 'session_summary' &&
      right.event_type !== 'session_summary'
    ) {
      return 1
    }
    if (
      right.event_type === 'session_summary' &&
      left.event_type !== 'session_summary'
    ) {
      return -1
    }
    return 0
  })
  const selected: PersonaIssueMarker[] = []

  for (const marker of preferred) {
    const markerTaskId = issueTaskId(marker)
    const markerDetail = normalizeIssueText(marker.detail ?? marker.summary)
    const markerSummary = normalizeIssueText(marker.summary)
    const isDuplicate = selected.some((existing) => {
      if (existing.primary_tag !== marker.primary_tag) {
        return false
      }
      if (
        (existing.primary_root_cause ?? '') !==
        (marker.primary_root_cause ?? '')
      ) {
        return false
      }
      if (existing.fingerprint && marker.fingerprint) {
        return existing.fingerprint === marker.fingerprint
      }
      const existingTaskId = issueTaskId(existing)
      if (existingTaskId && markerTaskId) {
        return existingTaskId === markerTaskId
      }
      const existingDetail = normalizeIssueText(
        existing.detail ?? existing.summary,
      )
      const existingSummary = normalizeIssueText(existing.summary)
      return (
        existingDetail === markerDetail ||
        existingDetail === markerSummary ||
        existingSummary === markerDetail ||
        existingDetail.includes(markerSummary) ||
        markerDetail.includes(existingSummary)
      )
    })
    if (!isDuplicate) {
      selected.push(marker)
    }
  }

  return selected
}

export function filterIssueMarkers(
  issueMarkers: PersonaIssueMarker[],
  tag: string | null,
): PersonaIssueMarker[] {
  const deduped = dedupeIssueMarkers(issueMarkers)
  if (!tag || tag === 'recovered') {
    return deduped
  }
  return deduped.filter((marker) => issueMarkerHasPulseTag(marker, tag))
}

export function visibleIssueMarkers(
  entry: PersonaStreamEntry,
  tag: string | null,
): PersonaIssueMarker[] {
  return filterIssueMarkers(entry.issue_markers, tag)
}
