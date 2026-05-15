'use client'

import { Loader2 } from 'lucide-react'
import { useMemo, useState } from 'react'

import type {
  PersonaIssueMarker,
  PersonaStreamEntry,
} from '@/lib/api/persona-stream'
import { cn } from '@/lib/utils'
import type { TimelineEvent } from '@/types/events'
import type { NarrationTag } from '../hooks/useNarrationTags'
import { getPersonaDisplayName } from '../utils/displayName'
import { pulseTagLabel } from './pulse-helpers'
import {
  buildSessionDetailBlocks,
  describeValue,
} from './workspace-event-details'
import type { DetailField } from './workspace-types'
import {
  isGenericStatusText,
  isPromptLikeText,
  isRecord,
  prettifyDisplayText,
} from './workspace-utils'

// ─── Strip observability tags from display text ───

const NARRATION_TAG_RE = /\[\[P:[a-z_]+(?::[^\]]*?)?\]?\]?/g
const APPLIED_CITATION_RE =
  /\s*(?:Applied:\s*)?\[(?:M|G|R):[a-f0-9]{3,8}[^\]]*\]?/g
const FEEDBACK_RE = /\[\[F:[^\]]*\]?\]?/g
const SUMMARY_RE = /\[\[S:[^\]]*\]?\]?/g

function cleanSummary(text: string | null | undefined): string {
  if (!text) return ''
  let cleaned = text
    .replace(NARRATION_TAG_RE, '')
    .replace(APPLIED_CITATION_RE, '')
    .replace(FEEDBACK_RE, '')
    .replace(SUMMARY_RE, '')
    .replace(/^HEARTBEAT_(?:OK|ACTION)\s*[—–-]?\s*/i, '')
  cleaned = cleaned
    .replace(/\[…/g, '')
    .replace(/^\[+\s*$/g, '')
    .replace(/\[+\s*\.\.\./g, '')
    .replace(/\.\.\./g, '…')
    .replace(/\n{2,}/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim()
  if (/^[[\]{}()…\s.,;:]*$/.test(cleaned)) return ''
  return cleaned
}

export function entrySummary(
  entry: Pick<
    PersonaStreamEntry,
    | 'display_summary'
    | 'summary_oneliner'
    | 'live_summary'
    | 'status'
    | 'live_status'
    | 'project_id'
  >,
  fallback: string,
): string {
  const orderedCandidates =
    entry.status === 'active' || entry.live_status === 'active'
      ? [entry.live_summary, entry.display_summary, entry.summary_oneliner]
      : [entry.display_summary, entry.summary_oneliner, entry.live_summary]
  for (const candidate of orderedCandidates) {
    const cleaned = cleanSummary(candidate)
    if (cleaned) return cleaned
  }
  return fallback
}

function isRedundantSummaryMessage(
  messageText: string | null | undefined,
  summaryText: string | null | undefined,
): boolean {
  const normalize = (text: string | null | undefined) =>
    cleanSummary(prettifyDisplayText(text || ''))
      .toLowerCase()
      .replace(/[`"""']/g, '')
      .replace(/[^a-z0-9]+/g, ' ')
      .trim()

  const message = normalize(messageText)
  const summary = normalize(summaryText)
  if (!message || !summary) return false
  if (message === summary) return true
  const shorter = message.length <= summary.length ? message : summary
  const longer = message.length > summary.length ? message : summary
  return shorter.length >= 72 && longer.includes(shorter)
}

// ─── Helpers for extracting human-readable text from events ───

function extractToolCallSummary(toolInput: unknown): string {
  if (!isRecord(toolInput)) return ''
  const keys = [
    'command',
    'action',
    'description',
    'file_path',
    'path',
    'query',
    'prompt',
    'slug',
    'pattern',
  ]
  for (const key of keys) {
    const val = describeValue(toolInput[key])
    if (val && val.length < 120) return `${key}="${val}"`
    if (val) return `${key}="${val.slice(0, 80)}…"`
  }
  return ''
}

function extractToolResult(toolOutput: unknown): string {
  if (typeof toolOutput === 'string')
    return prettifyDisplayText(toolOutput) || ''
  if (!isRecord(toolOutput)) return ''
  const keys = [
    'content',
    'summary',
    'stdout',
    'message',
    'error_message',
    'stderr',
  ]
  for (const key of keys) {
    const val = toolOutput[key]
    if (typeof val === 'string' && val.trim())
      return prettifyDisplayText(val) || ''
  }
  for (const val of Object.values(toolOutput)) {
    if (typeof val === 'string' && val.trim() && val.length < 300)
      return prettifyDisplayText(val) || ''
  }
  return ''
}

function isNoiseEvent(event: TimelineEvent): boolean {
  if (
    event.event_type === 'memory_inject' ||
    event.event_type === 'memory_cite'
  )
    return true
  if (
    event.event_type === 'system_message' ||
    event.event_type === 'user_message'
  )
    return true
  if (event.event_type === 'thinking') {
    const text = (event.content || '').toLowerCase()
    return (
      !text.includes('error') &&
      !text.includes('blocked') &&
      !text.includes('failed')
    )
  }
  if (event.event_type === 'assistant_message') {
    if (isPromptLikeText(event.content) || isGenericStatusText(event.content))
      return true
    if (!event.content || event.content.trim().length === 0) return true
    if (!cleanSummary(event.content)) return true
  }
  return false
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max)}…`
}

// ─── TranscriptItem types and builder ───

interface TranscriptItem {
  id: string
  timestamp: string
  kind: 'message' | 'tool_call' | 'error' | 'narration'
  content?: string
  toolName?: string
  toolParam?: string
  toolResult?: string
  toolResultFull?: string
  toolFields?: DetailField[]
  isError?: boolean
  tagType?: string
  tagContent?: string
}

function buildTranscriptItems(
  events: TimelineEvent[],
  narrationTags?: NarrationTag[],
): TranscriptItem[] {
  const items: TranscriptItem[] = []
  const processedIds = new Set<string>()

  for (let i = 0; i < events.length; i++) {
    const event = events[i]
    if (processedIds.has(event.id) || isNoiseEvent(event)) continue

    if (event.event_type === 'tool_use') {
      processedIds.add(event.id)
      const param = extractToolCallSummary(event.tool_input)
      let result = '',
        resultFull = '',
        hasError = false
      let toolFields: DetailField[] = []
      const next = events[i + 1]
      if (
        next?.event_type === 'tool_result' &&
        next.turn === event.turn &&
        next.tool_name === event.tool_name
      ) {
        processedIds.add(next.id)
        const raw = extractToolResult(next.tool_output)
        resultFull = raw
        result = truncate(raw, 150)
        const outputRecord = isRecord(next.tool_output)
          ? next.tool_output
          : null
        hasError =
          outputRecord?.is_error === true ||
          outputRecord?.exit_code === 1 ||
          (outputRecord?.status as string)?.toLowerCase() === 'failed' ||
          raw.toLowerCase().startsWith('error')
        toolFields =
          buildSessionDetailBlocks([event, next])[0]?.fields.slice(0, 6) ?? []
        i++
      } else {
        toolFields =
          buildSessionDetailBlocks([event])[0]?.fields.slice(0, 6) ?? []
      }
      items.push({
        id: event.id,
        timestamp: event.created_at,
        kind: 'tool_call',
        toolName: event.tool_name || 'tool',
        toolParam: param,
        toolResult: result,
        toolResultFull:
          resultFull.length > result.length ? resultFull : undefined,
        toolFields,
        isError: hasError,
      })
      continue
    }

    if (event.event_type === 'tool_result') {
      processedIds.add(event.id)
      const raw = extractToolResult(event.tool_output)
      const toolFields =
        buildSessionDetailBlocks([event])[0]?.fields.slice(0, 6) ?? []
      items.push({
        id: event.id,
        timestamp: event.created_at,
        kind: 'tool_call',
        toolName: event.tool_name || 'tool',
        toolResult: truncate(raw, 150),
        toolResultFull: raw.length > 150 ? raw : undefined,
        toolFields,
      })
      continue
    }

    if (event.event_type === 'error') {
      processedIds.add(event.id)
      items.push({
        id: event.id,
        timestamp: event.created_at,
        kind: 'error',
        content:
          prettifyDisplayText(event.content || 'Unknown error') ||
          'Unknown error',
      })
      continue
    }

    if (
      (event.event_type === 'assistant_message' ||
        event.event_type === 'thinking') &&
      event.content
    ) {
      processedIds.add(event.id)
      items.push({
        id: event.id,
        timestamp: event.created_at,
        kind: 'message',
        content: cleanSummary(prettifyDisplayText(event.content || '')),
      })
    }
  }

  if (narrationTags && narrationTags.length > 0) {
    for (const tag of narrationTags) {
      items.push({
        id: `narration-${tag.id}`,
        timestamp: tag.created_at,
        kind: 'narration',
        tagType: tag.tag_type,
        tagContent: tag.content,
      })
    }
  }

  items.sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
  )
  return items
}

const NARRATION_ICONS: Record<string, string> = {
  started: '▸',
  found: '🔍',
  modified: '✏️',
  tested: '✓',
  confidence: '📊',
  blocked: '⚠',
  decision: '⚖️',
}

// ─── Sub-components ───

function ExpandButton({
  expanded,
  onClick,
}: {
  expanded: boolean
  onClick: (e: React.MouseEvent) => void
}) {
  return (
    <button
      onClick={onClick}
      className="ml-1.5 rounded bg-slate-800/40 px-1.5 py-0.5 text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
    >
      {expanded ? 'less' : 'more'}
    </button>
  )
}

function MessageItem({ item, name }: { item: TranscriptItem; name: string }) {
  const [expanded, setExpanded] = useState(false)
  const isLong = item.content && item.content.length > 200

  return (
    <div className="text-xs leading-relaxed py-0.5">
      <span className="font-medium text-slate-300">{name}:</span>{' '}
      <span className="text-slate-400/90">
        {isLong ? (
          expanded ? (
            <>
              <span className="whitespace-pre-wrap">{item.content}</span>
              <ExpandButton
                expanded
                onClick={(e) => {
                  e.stopPropagation()
                  setExpanded(false)
                }}
              />
            </>
          ) : (
            <>
              {truncate(item.content!, 200)}
              <ExpandButton
                expanded={false}
                onClick={(e) => {
                  e.stopPropagation()
                  setExpanded(true)
                }}
              />
            </>
          )
        ) : (
          item.content
        )}
      </span>
    </div>
  )
}

function ToolCallItem({ item }: { item: TranscriptItem }) {
  const [expanded, setExpanded] = useState(false)
  const paramStr = item.toolParam ? `(${item.toolParam})` : ''

  return (
    <div className="text-xs font-mono rounded-md bg-slate-800/20 px-2.5 py-1.5">
      <div className="text-slate-400">
        <span
          className={cn(
            'inline-block h-1.5 w-1.5 rounded-full mr-1.5',
            item.isError ? 'bg-rose-400' : 'bg-slate-600',
          )}
        />
        Ran <span className="text-slate-300 font-medium">{item.toolName}</span>
        {paramStr && <span className="text-slate-500">{paramStr}</span>}
      </div>
      {item.toolResult && (
        <div
          className={cn(
            'ml-4 mt-1 border-l border-slate-800/50 pl-2.5',
            item.isError ? 'text-rose-400/80' : 'text-slate-500',
          )}
        >
          {item.toolResultFull && !expanded ? (
            <>
              {item.toolResult}
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setExpanded(true)
                }}
                className="ml-1.5 text-slate-600 hover:text-slate-400 font-sans text-[10px]"
              >
                more
              </button>
            </>
          ) : item.toolResultFull && expanded ? (
            <>
              <span className="whitespace-pre-wrap break-words font-sans">
                {item.toolResultFull}
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  setExpanded(false)
                }}
                className="ml-1.5 text-slate-600 hover:text-slate-400 font-sans text-[10px]"
              >
                less
              </button>
            </>
          ) : (
            item.toolResult
          )}
        </div>
      )}
      {item.toolFields && item.toolFields.length > 0 && (
        <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
          {item.toolFields.map((field) => (
            <div
              key={`${item.id}-${field.label}-${field.value}`}
              className="rounded-md border border-slate-800/60 bg-slate-950/60 px-2 py-1.5 font-sans"
            >
              <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
                {field.label}
              </div>
              <div
                className={cn(
                  'mt-1 break-words text-[11px]',
                  field.tone === 'danger'
                    ? 'text-rose-300'
                    : field.tone === 'warning'
                      ? 'text-amber-300'
                      : field.tone === 'success'
                        ? 'text-emerald-300'
                        : field.tone === 'info'
                          ? 'text-sky-300'
                          : 'text-slate-300',
                )}
              >
                {field.value}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ErrorItem({ item }: { item: TranscriptItem }) {
  return (
    <div className="text-xs text-rose-400/80 rounded-md bg-rose-500/5 px-2.5 py-1.5 flex items-start gap-2">
      <span className="text-rose-500/60 mt-0.5">⚠</span>
      <span>{item.content}</span>
    </div>
  )
}

function NarrationItem({ item }: { item: TranscriptItem }) {
  const icon = NARRATION_ICONS[item.tagType || ''] || '▸'

  if (item.tagType === 'confidence') {
    const match = (item.tagContent || '').match(/^(\d+)/)
    const pct = match ? parseInt(match[1], 10) : null
    const rest = (item.tagContent || '').replace(/^\d+\s*[-–—:]\s*/, '')
    return (
      <div className="text-xs text-violet-400/80 flex items-center gap-2 py-0.5">
        <span className="text-violet-500/60">{icon}</span>
        {pct !== null && (
          <>
            <div className="h-1.5 w-14 rounded-full bg-slate-800/60 overflow-hidden">
              <div
                className={cn(
                  'h-full rounded-full transition-all',
                  pct >= 70
                    ? 'bg-emerald-500/70'
                    : pct >= 40
                      ? 'bg-amber-500/70'
                      : 'bg-rose-500/70',
                )}
                style={{ width: `${Math.min(pct, 100)}%` }}
              />
            </div>
            <span className="font-medium tabular-nums">{pct}%</span>
          </>
        )}
        {rest && <span className="text-slate-500">{rest}</span>}
      </div>
    )
  }

  return (
    <div
      className={cn(
        'text-xs py-0.5',
        item.tagType === 'blocked' ? 'text-rose-400/80' : 'text-slate-400/80',
      )}
    >
      <span
        className={
          item.tagType === 'blocked' ? 'text-rose-500/60' : 'text-slate-500/60'
        }
      >
        {icon}
      </span>{' '}
      <span className="font-medium capitalize">{item.tagType}:</span>{' '}
      {item.tagContent}
    </div>
  )
}

function IssueMarkerList({ markers }: { markers: PersonaIssueMarker[] }) {
  return (
    <div className="mt-3 space-y-1.5 border-t border-slate-800/30 pt-2.5">
      {markers.map((marker) => (
        <div
          key={`issue-${marker.event_id}-${marker.primary_tag}`}
          className="flex items-start gap-2 text-xs text-amber-400/80"
        >
          <span className="text-amber-500/60 mt-0.5">⚠</span>
          <div>
            <span className="font-medium">
              {pulseTagLabel(marker.primary_tag)}:
            </span>{' '}
            {marker.title}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── SessionTranscript: chronological chat-like event stream ───

export function SessionTranscript({
  events,
  narrationTags,
  narrationLoading,
  issueMarkers,
  personaName,
  summaryText,
  hideRedundantSummaryMessage = false,
}: {
  events: TimelineEvent[]
  narrationTags?: NarrationTag[]
  narrationLoading?: boolean
  issueMarkers?: PersonaIssueMarker[]
  personaName?: string
  summaryText?: string
  hideRedundantSummaryMessage?: boolean
}) {
  const items = useMemo(() => {
    const transcriptItems = buildTranscriptItems(events, narrationTags)
    if (!hideRedundantSummaryMessage || !summaryText) return transcriptItems
    return transcriptItems.filter(
      (item) =>
        item.kind !== 'message' ||
        !isRedundantSummaryMessage(item.content, summaryText),
    )
  }, [events, hideRedundantSummaryMessage, narrationTags, summaryText])

  if (narrationLoading) {
    return (
      <div className="mt-3 flex items-center gap-2 border-t border-slate-800/40 pt-3 text-xs text-slate-600">
        <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500/50" />
        Loading transcript...
      </div>
    )
  }

  if (items.length === 0) {
    return (
      <div className="mt-3 rounded-lg border border-slate-800/30 bg-slate-900/20 px-3.5 py-2.5 text-xs text-slate-600">
        No detailed activity recorded.
      </div>
    )
  }

  const name = getPersonaDisplayName(personaName)

  return (
    <div className="mt-3 border-t border-slate-800/40 pt-3 space-y-2">
      {items.map((item) => {
        switch (item.kind) {
          case 'message':
            return <MessageItem key={item.id} item={item} name={name} />
          case 'tool_call':
            return <ToolCallItem key={item.id} item={item} />
          case 'error':
            return <ErrorItem key={item.id} item={item} />
          case 'narration':
            return <NarrationItem key={item.id} item={item} />
          default:
            return null
        }
      })}

      {issueMarkers && issueMarkers.length > 0 && (
        <IssueMarkerList markers={issueMarkers} />
      )}
    </div>
  )
}
