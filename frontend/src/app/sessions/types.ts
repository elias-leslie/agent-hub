import type { SessionKind } from '@/lib/api/sessions'

export type SortField = 'last_active' | 'status'
export type SortDirection = 'asc' | 'desc'

export type StatusFilter = '' | 'running' | 'completed' | 'failed'
export type SincePreset = 'today' | '7d' | '30d' | 'all'

/** Everything the list shows is derived from this; it round-trips through the URL. */
export interface SessionListState {
  q: string
  kinds: SessionKind[]
  status: StatusFilter
  since: SincePreset
  project: string
  model: string
  includeSubagents: boolean
  includeBenchmarks: boolean
  sort: SortField
  selected: string | null
}

export const DEFAULT_KINDS: SessionKind[] = ['coding', 'chat']

export const DEFAULT_LIST_STATE: SessionListState = {
  q: '',
  kinds: DEFAULT_KINDS,
  status: '',
  since: 'all',
  project: '',
  model: '',
  includeSubagents: false,
  includeBenchmarks: false,
  sort: 'last_active',
  selected: null,
}

export const KIND_LABELS: Record<SessionKind, string> = {
  coding: 'Coding agents',
  chat: 'Chat',
  completion: 'Completions',
  image: 'Images',
}

export const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'running', label: 'Running' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
]

export const SINCE_OPTIONS: { value: SincePreset; label: string }[] = [
  { value: 'today', label: 'Today' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: 'all', label: 'All time' },
]
