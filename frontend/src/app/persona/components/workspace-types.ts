import type { ChatMessage } from '@agent-hub/chat-ui'
import type {
  PersonaPulseSummary,
  PersonaStreamEntry,
  PersonaStreamEventPreview,
} from '@/lib/api/persona-stream'
import type { TimelineEvent } from '@/types/events'

export const PROJECT_ID = 'persona-sandbox'
export const PAGE_SIZE = 120
export const LIVE_REFRESH_MS = 5_000
export const AUTO_FOLLOW_BOTTOM_THRESHOLD = 160
export const PROGRAMMATIC_SCROLL_GRACE_MS = 400

export type FeedMessage = {
  kind: 'message'
  id: string
  sessionId: string | null
  timestamp: Date
  message: ChatMessage
}
export type FeedHeartbeat = {
  kind: 'heartbeat'
  id: string
  sessionId: string
  timestamp: Date
  entry: PersonaStreamEntry
}
export type FeedChildRun = {
  kind: 'child_run'
  id: string
  sessionId: string
  timestamp: Date
  entry: PersonaStreamEntry
}
export type FeedAnchor = FeedMessage | FeedHeartbeat | FeedChildRun
export type FeedItem = FeedAnchor

export interface ItemTimelineBlock {
  kind: 'item'
  anchorItem: FeedAnchor
  childRuns: FeedChildRun[]
}

export interface RoutineHeartbeatTimelineBlock {
  kind: 'routine_group'
  id: string
  items: Array<{
    anchorItem: FeedHeartbeat
    childRuns: FeedChildRun[]
  }>
}

export type TimelineBlock = ItemTimelineBlock | RoutineHeartbeatTimelineBlock

export interface LiveSessionPatch {
  liveSummary: string | null
  liveStatus: string | null
  eventPreviews: PersonaStreamEventPreview[]
}

export interface PreviewBadge {
  label: string
  tone?: 'neutral' | 'info' | 'success' | 'warning' | 'danger'
}

export interface SessionEventDetailsState {
  loading: boolean
  error: string | null
  events: TimelineEvent[]
}

export interface DetailField {
  label: string
  value: string
  tone?: 'neutral' | 'info' | 'success' | 'warning' | 'danger'
}

export interface SessionDetailBlock {
  id: string
  timestamp: string
  eventType: string
  label: string
  title: string | null
  lead: string | null
  textBlocks: string[]
  fields: DetailField[]
  score: number
  defaultVisible: boolean
}

export const EMPTY_PULSE: PersonaPulseSummary = {
  metrics: [],
  issue_groups: [],
  agent_scorecards: [],
}

export type TimelineRow =
  | { kind: 'divider'; id: string; label: string }
  | { kind: 'unread'; id: string }
  | { kind: 'routine_group'; id: string; block: RoutineHeartbeatTimelineBlock }
  | { kind: 'item'; id: string; item: FeedAnchor; childRuns: FeedChildRun[] }
