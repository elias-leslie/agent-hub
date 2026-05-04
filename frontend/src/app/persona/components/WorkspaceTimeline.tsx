'use client'

import { type ChatMessage, MessageBubble } from '@agent-hub/chat-ui'
import type { Virtualizer } from '@tanstack/react-virtual'
import { AlertCircle, CircleDot, HeartPulse, Loader2 } from 'lucide-react'
import type { RefObject } from 'react'
import type {
  PersonaPulseMetric,
  PersonaPulseSummary,
} from '@/lib/api/persona-stream'
import { cn } from '@/lib/utils'
import type { NarrationTag } from '../hooks/useNarrationTags'
import type { FilterMode } from './pulse-helpers'
import {
  ChildRunCard,
  ChildRunStack,
  HeartbeatCard,
  PulseOverviewPanels,
  RoutineHeartbeatGroup,
} from './workspace-cards'
import type {
  FeedAnchor,
  FeedChildRun,
  SessionEventDetailsState,
  TimelineRow,
} from './workspace-types'
import { DateDivider, TimelineTimestamp } from './workspace-utils'

type NarrationCache = Record<
  string,
  { tags: NarrationTag[]; loading: boolean; error: string | null }
>

interface WorkspaceTimelineProps {
  scrollRef: RefObject<HTMLDivElement | null>
  loading: boolean
  error: string | null
  chatError: string | null
  groupedItems: Array<{ label: string; blocks: unknown[] }>
  timelineRows: TimelineRow[]
  virtualizer: Virtualizer<HTMLDivElement, Element>
  visiblePulseMetrics: PersonaPulseMetric[]
  pulse: PersonaPulseSummary
  applyPulseFilter: (mode: FilterMode, anchorEntryId?: string | null) => void
  inspectAgentPulse: (agentSlug: string) => void
  selectedSessionId: string | null
  activeIssueTag: string | null
  expandedEntryIds: Record<string, boolean>
  expandedRoutineGroupIds: Record<string, boolean>
  matchedIds: Set<string>
  activeMatchId: string | null
  sessionEventDetails: Record<string, SessionEventDetailsState>
  narrationCache: NarrationCache
  personaDisplayName: string
  total: number
  entries: unknown[]
  deferredSearch: string
  status: string
  autoFollow: boolean
  isAtBottom: boolean
  newActivityCount: number
  latestItemId: string | null
  onToggleEntry: (
    entryId: string,
    sessionId?: string,
    externalId?: string,
  ) => void
  onToggleRoutineGroup: (groupId: string) => void
  onLoadOlder: () => void
  onJumpToLatest: () => void
  showPulseOverview?: boolean
  compactViewport?: boolean
}

export function WorkspaceTimeline({
  scrollRef,
  loading,
  error,
  chatError,
  groupedItems,
  timelineRows,
  virtualizer,
  visiblePulseMetrics,
  pulse,
  applyPulseFilter,
  inspectAgentPulse,
  selectedSessionId,
  activeIssueTag,
  expandedEntryIds,
  expandedRoutineGroupIds,
  matchedIds,
  activeMatchId,
  sessionEventDetails,
  narrationCache,
  personaDisplayName,
  total,
  entries,
  deferredSearch,
  status,
  onToggleEntry,
  onToggleRoutineGroup,
  onLoadOlder,
  showPulseOverview = true,
  compactViewport = false,
}: WorkspaceTimelineProps) {
  const renderVirtualRows = false
  const virtualRows = virtualizer.getVirtualItems()

  const renderedRows = renderVirtualRows
    ? virtualRows.map((virtualRow) => ({
        key: virtualRow.key,
        row: timelineRows[virtualRow.index],
        start: virtualRow.start,
        measure: true,
      }))
    : timelineRows.map((row, index) => ({
        key: `${row.id}:${index}`,
        row,
        start: 0,
        measure: false,
      }))

  return (
    <div
      ref={scrollRef}
      data-testid="stream-scroll-container"
      className={cn(
        'flex-1 overflow-y-auto bg-slate-950',
        compactViewport
          ? 'px-4 py-3 pb-40 sm:pb-44'
          : 'px-5 py-5 pb-16 lg:pb-20',
      )}
    >
      {showPulseOverview ? (
        <div className="mx-auto max-w-4xl">
          <PulseOverviewPanels
            visiblePulseMetrics={visiblePulseMetrics}
            pulse={pulse}
            applyPulseFilter={applyPulseFilter}
            inspectAgentPulse={inspectAgentPulse}
          />
        </div>
      ) : null}

      {(error || chatError) && (
        <div className="mb-4 flex items-center gap-2.5 rounded-xl border border-rose-500/20 bg-rose-950/20 px-4 py-2.5 text-sm text-rose-300/90">
          <AlertCircle className="h-4 w-4 flex-shrink-0 text-rose-400" />
          {error || chatError}
        </div>
      )}

      {loading && (entries as unknown[]).length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-slate-500 gap-3">
          <Loader2 className="h-5 w-5 animate-spin text-amber-500/60" />
          <span className="text-xs text-slate-600">Loading activity...</span>
        </div>
      ) : groupedItems.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 gap-3">
          <div className="rounded-full bg-slate-800/50 p-4">
            <HeartPulse className="h-6 w-6 text-slate-600" />
          </div>
          <p className="text-sm font-medium text-slate-500">No activity yet</p>
          <p className="text-xs text-slate-600 max-w-xs text-center">
            {personaDisplayName} hasn&apos;t had any heartbeats or conversations
            in this time range.
          </p>
        </div>
      ) : (
        <div className="mx-auto max-w-4xl">
          {total > (entries as unknown[]).length && !deferredSearch.trim() && (
            <div className="flex justify-center pt-2 pb-8">
              <button
                onClick={onLoadOlder}
                className="rounded-lg border border-slate-700/50 bg-slate-800/40 px-5 py-2.5 text-xs font-medium text-slate-400 transition-all hover:bg-slate-800/70 hover:text-slate-200 hover:border-slate-600/50"
              >
                Load older entries
              </button>
            </div>
          )}
          <div
            className="relative w-full space-y-1.5"
            style={
              renderVirtualRows
                ? { height: `${virtualizer.getTotalSize()}px` }
                : undefined
            }
          >
            {renderedRows.map(({ key, row, start, measure }) => {
              if (!row) return null
              return (
                <TimelineRowRenderer
                  key={key}
                  row={row}
                  start={start}
                  measure={measure}
                  virtualizer={virtualizer}
                  renderVirtualRows={renderVirtualRows}
                  selectedSessionId={selectedSessionId}
                  activeIssueTag={activeIssueTag}
                  expandedEntryIds={expandedEntryIds}
                  expandedRoutineGroupIds={expandedRoutineGroupIds}
                  matchedIds={matchedIds}
                  activeMatchId={activeMatchId}
                  sessionEventDetails={sessionEventDetails}
                  narrationCache={narrationCache}
                  personaDisplayName={personaDisplayName}
                  status={status}
                  onToggleEntry={onToggleEntry}
                  onToggleRoutineGroup={onToggleRoutineGroup}
                />
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

interface TimelineRowRendererProps {
  row: TimelineRow
  start: number
  measure: boolean
  virtualizer: Virtualizer<HTMLDivElement, Element>
  renderVirtualRows: boolean
  selectedSessionId: string | null
  activeIssueTag: string | null
  expandedEntryIds: Record<string, boolean>
  expandedRoutineGroupIds: Record<string, boolean>
  matchedIds: Set<string>
  activeMatchId: string | null
  sessionEventDetails: Record<string, SessionEventDetailsState>
  narrationCache: NarrationCache
  personaDisplayName: string
  status: string
  onToggleEntry: (
    entryId: string,
    sessionId?: string,
    externalId?: string,
  ) => void
  onToggleRoutineGroup: (groupId: string) => void
}

function TimelineRowRenderer({
  row,
  start,
  measure,
  virtualizer,
  renderVirtualRows,
  selectedSessionId,
  activeIssueTag,
  expandedEntryIds,
  expandedRoutineGroupIds,
  matchedIds,
  activeMatchId,
  sessionEventDetails,
  narrationCache,
  personaDisplayName,
  status,
  onToggleEntry,
  onToggleRoutineGroup,
}: TimelineRowRendererProps) {
  const wrapperClass = cn(renderVirtualRows && 'absolute left-0 top-0 w-full')
  const wrapperStyle = renderVirtualRows
    ? { transform: `translateY(${start}px)` }
    : undefined
  const measureRef = measure ? virtualizer.measureElement : undefined

  if (row.kind === 'divider') {
    return (
      <div ref={measureRef} className={wrapperClass} style={wrapperStyle}>
        <DateDivider label={row.label} />
      </div>
    )
  }

  if (row.kind === 'unread') {
    return (
      <div ref={measureRef} className={wrapperClass} style={wrapperStyle}>
        <div
          data-testid="new-activity-separator"
          className="flex items-center gap-3 py-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-amber-400/80"
        >
          <div className="h-px flex-1 bg-gradient-to-r from-transparent to-amber-500/20" />
          <span className="inline-flex items-center gap-1.5 rounded-md bg-amber-500/10 px-2.5 py-1">
            <CircleDot className="h-3 w-3" />
            New activity
          </span>
          <div className="h-px flex-1 bg-gradient-to-l from-transparent to-amber-500/20" />
        </div>
      </div>
    )
  }

  if (row.kind === 'routine_group') {
    return (
      <div ref={measureRef} className={wrapperClass} style={wrapperStyle}>
        <RoutineHeartbeatGroup
          block={row.block}
          expanded={!!expandedRoutineGroupIds[row.block.id]}
          onToggle={() => onToggleRoutineGroup(row.block.id)}
          activeSessionId={selectedSessionId}
          activeIssueTag={activeIssueTag}
          expandedEntryIds={expandedEntryIds}
          onToggleEntry={(entryId, sessionId) => {
            const entry = row.block.items.find(
              (it) => it.anchorItem.id === entryId,
            )
            onToggleEntry(
              entryId,
              sessionId,
              entry?.anchorItem.entry.external_id ?? undefined,
            )
          }}
          sessionEventDetails={sessionEventDetails}
          narrationCache={narrationCache}
          personaName={personaDisplayName}
        />
      </div>
    )
  }

  // row.kind === "item"
  const item = row.item
  const selected = !!item.sessionId && item.sessionId === selectedSessionId
  const matched = matchedIds.has(item.id)
  const activeMatched = activeMatchId === item.id
  const baseClasses = cn(
    'flex items-start gap-3 rounded-xl',
    matched && 'px-2.5 py-1.5 ring-1 ring-amber-600/30 bg-amber-950/5',
    activeMatched && 'ring-2 ring-amber-500/50 bg-amber-950/10',
  )
  const isStreaming = status !== 'idle' && status !== 'error'

  return (
    <div ref={measureRef} className={wrapperClass} style={wrapperStyle}>
      {item.kind === 'message' ? (
        <MessageItem
          item={item}
          selected={selected}
          matched={matched}
          activeMatched={activeMatched}
          isStreaming={isStreaming}
          childRuns={row.childRuns}
          selectedSessionId={selectedSessionId}
          activeIssueTag={activeIssueTag}
          expandedEntryIds={expandedEntryIds}
          matchedIds={matchedIds}
          activeMatchId={activeMatchId}
          sessionEventDetails={sessionEventDetails}
          narrationCache={narrationCache}
          personaDisplayName={personaDisplayName}
          onToggleEntry={onToggleEntry}
        />
      ) : item.kind === 'child_run' ? (
        <div
          data-session-anchor={item.sessionId}
          data-testid="stream-item"
          data-stream-item-id={item.id}
          data-timestamp={item.timestamp.toISOString()}
          className={baseClasses}
        >
          <TimelineTimestamp timestamp={item.timestamp} />
          <div className="min-w-0 flex-1">
            <ChildRunCard
              entry={item.entry}
              activeIssueTag={activeIssueTag}
              selected={selected}
              expanded={!!expandedEntryIds[item.id]}
              onToggle={() =>
                onToggleEntry(
                  item.id,
                  item.sessionId,
                  item.entry.external_id ?? undefined,
                )
              }
              details={sessionEventDetails[item.sessionId]}
              narrationTags={
                item.entry.external_id
                  ? narrationCache[item.entry.external_id]?.tags
                  : undefined
              }
              narrationLoading={
                item.entry.external_id
                  ? narrationCache[item.entry.external_id]?.loading
                  : undefined
              }
              personaName={personaDisplayName}
            />
          </div>
        </div>
      ) : (
        <div
          data-session-anchor={item.sessionId}
          data-testid="stream-item"
          data-stream-item-id={item.id}
          data-timestamp={item.timestamp.toISOString()}
          className={baseClasses}
        >
          <TimelineTimestamp timestamp={item.timestamp} />
          <div className="min-w-0 flex-1">
            <HeartbeatCard
              entry={item.entry}
              activeIssueTag={activeIssueTag}
              selected={selected}
              expanded={!!expandedEntryIds[item.id]}
              onToggle={() =>
                onToggleEntry(
                  item.id,
                  item.sessionId,
                  item.entry.external_id ?? undefined,
                )
              }
              details={sessionEventDetails[item.sessionId]}
              narrationTags={
                item.entry.external_id
                  ? narrationCache[item.entry.external_id]?.tags
                  : undefined
              }
              narrationLoading={
                item.entry.external_id
                  ? narrationCache[item.entry.external_id]?.loading
                  : undefined
              }
              personaName={personaDisplayName}
            />
            {row.childRuns.length > 0 && (
              <ChildRunStack
                childRuns={row.childRuns}
                activeSessionId={selectedSessionId}
                activeIssueTag={activeIssueTag}
                expandedEntryIds={expandedEntryIds}
                onToggle={(entryId, sessionId) => {
                  const cr = row.childRuns.find((c) => c.id === entryId)
                  onToggleEntry(
                    entryId,
                    sessionId,
                    cr?.entry.external_id ?? undefined,
                  )
                }}
                matchedIds={matchedIds}
                activeMatchId={activeMatchId}
                sessionEventDetails={sessionEventDetails}
                narrationCache={narrationCache}
                personaName={personaDisplayName}
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

interface MessageItemProps {
  item: FeedAnchor & { kind: 'message'; message: ChatMessage }
  selected: boolean
  matched: boolean
  activeMatched: boolean
  isStreaming: boolean
  childRuns: FeedChildRun[]
  selectedSessionId: string | null
  activeIssueTag: string | null
  expandedEntryIds: Record<string, boolean>
  matchedIds: Set<string>
  activeMatchId: string | null
  sessionEventDetails: Record<string, SessionEventDetailsState>
  narrationCache: NarrationCache
  personaDisplayName: string
  onToggleEntry: (
    entryId: string,
    sessionId?: string,
    externalId?: string,
  ) => void
}

function MessageItem({
  item,
  selected,
  matched,
  activeMatched,
  isStreaming,
  childRuns,
  selectedSessionId,
  activeIssueTag,
  expandedEntryIds,
  matchedIds,
  activeMatchId,
  sessionEventDetails,
  narrationCache,
  personaDisplayName,
  onToggleEntry,
}: MessageItemProps) {
  return (
    <div
      data-session-anchor={item.sessionId ?? undefined}
      data-testid="stream-item"
      data-stream-item-id={item.id}
      data-timestamp={item.timestamp.toISOString()}
      className={cn(
        'flex items-start gap-3',
        selected && 'rounded-xl bg-sky-950/10 px-2.5 py-1.5',
        matched &&
          'rounded-xl px-2.5 py-1.5 ring-1 ring-amber-600/30 bg-amber-950/5',
        activeMatched && 'ring-2 ring-amber-500/50 bg-amber-950/10',
      )}
    >
      <TimelineTimestamp timestamp={item.timestamp} />
      <div className="min-w-0 flex-1">
        <MessageBubble
          message={item.message}
          isStreaming={isStreaming}
          canEdit={false}
          canRegenerate={false}
        />
        {childRuns.length > 0 && (
          <ChildRunStack
            childRuns={childRuns}
            activeSessionId={selectedSessionId}
            activeIssueTag={activeIssueTag}
            expandedEntryIds={expandedEntryIds}
            onToggle={(entryId, sessionId) => {
              const cr = childRuns.find((c) => c.id === entryId)
              onToggleEntry(
                entryId,
                sessionId,
                cr?.entry.external_id ?? undefined,
              )
            }}
            matchedIds={matchedIds}
            activeMatchId={activeMatchId}
            sessionEventDetails={sessionEventDetails}
            narrationCache={narrationCache}
            personaName={personaDisplayName}
          />
        )}
      </div>
    </div>
  )
}
