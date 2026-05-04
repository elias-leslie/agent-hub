'use client'

import {
  Bot,
  ChevronDown,
  Clock3,
  HeartPulse,
  Loader2,
  Wrench,
} from 'lucide-react'

import type {
  PersonaIssueMarker,
  PersonaStreamEntry,
} from '@/lib/api/persona-stream'
import { cn } from '@/lib/utils'
import type { NarrationTag } from '../hooks/useNarrationTags'
import { getPersonaDisplayName } from '../utils/displayName'
import {
  pulseTagClasses,
  pulseTagLabel,
  visibleIssueMarkers,
} from './pulse-helpers'
import { entrySummary, SessionTranscript } from './workspace-transcript'
import type {
  FeedChildRun,
  RoutineHeartbeatTimelineBlock,
  SessionEventDetailsState,
} from './workspace-types'
import {
  entryStatusClasses,
  formatTimeLabel,
  TimelineTimestamp,
} from './workspace-utils'

export type { FilterMode } from './pulse-helpers'
export { PulseOverviewPanels } from './workspace-pulse-panels'

// ─── EntryIssueSummary (compact inline on collapsed card) ───

export function EntryIssueSummary({
  issueMarkers,
}: {
  issueMarkers: PersonaIssueMarker[]
}) {
  const primaryMarker = issueMarkers[0]
  if (!primaryMarker) return null
  return (
    <div className="mt-2 flex items-center gap-2">
      <span
        className={cn(
          'rounded-md px-2 py-0.5 text-[10px] font-medium',
          pulseTagClasses(primaryMarker.primary_tag),
        )}
      >
        {pulseTagLabel(primaryMarker.primary_tag)}
      </span>
      <span className="text-[10px] text-slate-500 truncate">
        {primaryMarker.title}
      </span>
    </div>
  )
}

// ─── Shared loading / error states for expanded cards ───

function TranscriptLoading() {
  return (
    <div className="mt-3 flex items-center gap-2 border-t border-slate-800/40 pt-3 text-xs text-slate-600">
      <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-500/50" />
      Loading transcript...
    </div>
  )
}

function TranscriptError({ message }: { message: string }) {
  return (
    <div className="mt-3 rounded-lg border border-rose-500/20 bg-rose-950/15 px-3.5 py-2.5 text-xs text-rose-400/80">
      {message}
    </div>
  )
}

// ─── RoutineHeartbeatGroup ───

export function RoutineHeartbeatGroup({
  block,
  expanded,
  onToggle,
  activeSessionId,
  activeIssueTag,
  expandedEntryIds,
  onToggleEntry,
  sessionEventDetails,
  narrationCache,
  personaName,
}: {
  block: RoutineHeartbeatTimelineBlock
  expanded: boolean
  onToggle: () => void
  activeSessionId: string | null
  activeIssueTag: string | null
  expandedEntryIds: Record<string, boolean>
  onToggleEntry: (entryId: string, sessionId: string) => void
  sessionEventDetails: Record<string, SessionEventDetailsState>
  narrationCache?: Record<
    string,
    { tags: NarrationTag[]; loading: boolean; error: string | null }
  >
  personaName?: string
}) {
  const first = block.items[0]?.anchorItem
  const last = block.items.at(-1)?.anchorItem
  const timeRange =
    first && last
      ? `${formatTimeLabel(first.timestamp)} \u2013 ${formatTimeLabel(last.timestamp)}`
      : null

  return (
    <div className="rounded-xl border border-slate-800/30 bg-slate-900/15 px-3.5 py-2.5">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 transition-colors hover:text-slate-300"
      >
        <div className="flex items-center gap-2.5">
          <Clock3 className="h-3.5 w-3.5 text-slate-600" />
          <span className="text-xs font-medium text-slate-500">
            {block.items.length} routine heartbeats
          </span>
          {timeRange && (
            <span className="text-[10px] text-slate-600 font-mono tabular-nums">
              {timeRange}
            </span>
          )}
        </div>
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 text-slate-600 transition-transform duration-200',
            !expanded && '-rotate-90',
          )}
        />
      </button>
      {expanded && (
        <div className="mt-2.5 space-y-2 border-t border-slate-800/30 pt-2.5">
          {block.items.map(({ anchorItem }) => (
            <div
              key={anchorItem.id}
              data-session-anchor={anchorItem.sessionId}
              data-testid="stream-item"
              data-stream-item-id={anchorItem.id}
              data-timestamp={anchorItem.timestamp.toISOString()}
              className="flex items-start gap-3"
            >
              <TimelineTimestamp timestamp={anchorItem.timestamp} />
              <div className="min-w-0 flex-1">
                <HeartbeatCard
                  entry={anchorItem.entry}
                  activeIssueTag={activeIssueTag}
                  selected={anchorItem.sessionId === activeSessionId}
                  expanded={!!expandedEntryIds[anchorItem.id]}
                  onToggle={() =>
                    onToggleEntry(anchorItem.id, anchorItem.sessionId)
                  }
                  details={sessionEventDetails[anchorItem.sessionId]}
                  narrationTags={
                    anchorItem.entry.external_id
                      ? narrationCache?.[anchorItem.entry.external_id]?.tags
                      : undefined
                  }
                  narrationLoading={
                    anchorItem.entry.external_id
                      ? narrationCache?.[anchorItem.entry.external_id]?.loading
                      : undefined
                  }
                  personaName={personaName}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── ChildRunStack ───

export function ChildRunStack({
  childRuns,
  activeSessionId,
  activeIssueTag,
  expandedEntryIds,
  onToggle,
  matchedIds,
  activeMatchId,
  sessionEventDetails,
  narrationCache,
  personaName,
}: {
  childRuns: FeedChildRun[]
  activeSessionId: string | null
  activeIssueTag: string | null
  expandedEntryIds: Record<string, boolean>
  onToggle: (entryId: string, sessionId: string) => void
  matchedIds: Set<string>
  activeMatchId: string | null
  sessionEventDetails: Record<string, SessionEventDetailsState>
  narrationCache?: Record<
    string,
    { tags: NarrationTag[]; loading: boolean; error: string | null }
  >
  personaName?: string
}) {
  return (
    <div className="ml-5 mt-2.5 border-l border-sky-800/30 pl-3.5">
      <div className="space-y-2.5">
        {childRuns.map((childRun) => (
          <div
            key={childRun.id}
            data-session-anchor={childRun.sessionId}
            data-testid="stream-item"
            data-stream-item-id={childRun.id}
            data-timestamp={childRun.timestamp.toISOString()}
            className={cn(
              'flex items-start gap-2 rounded-xl',
              matchedIds.has(childRun.id) &&
                'px-2.5 py-1.5 ring-1 ring-amber-600/30 bg-amber-950/5',
              activeMatchId === childRun.id &&
                'ring-2 ring-amber-500/50 bg-amber-950/10',
            )}
          >
            <div className="min-w-0 flex-1">
              <ChildRunCard
                entry={childRun.entry}
                activeIssueTag={activeIssueTag}
                selected={childRun.sessionId === activeSessionId}
                expanded={!!expandedEntryIds[childRun.id]}
                onToggle={() => onToggle(childRun.id, childRun.sessionId)}
                details={sessionEventDetails[childRun.sessionId]}
                narrationTags={
                  childRun.entry.external_id
                    ? narrationCache?.[childRun.entry.external_id]?.tags
                    : undefined
                }
                narrationLoading={
                  childRun.entry.external_id
                    ? narrationCache?.[childRun.entry.external_id]?.loading
                    : undefined
                }
                personaName={personaName}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Shared card props ───

interface CardProps {
  entry: PersonaStreamEntry
  activeIssueTag: string | null
  selected: boolean
  expanded: boolean
  onToggle: () => void
  details?: SessionEventDetailsState
  narrationTags?: NarrationTag[]
  narrationLoading?: boolean
  personaName?: string
}

// ─── ChildRunCard (compact) ───

export function ChildRunCard({
  entry,
  activeIssueTag,
  selected,
  expanded,
  onToggle,
  details,
  narrationTags,
  narrationLoading,
  personaName,
}: CardProps) {
  const issueMarkers = visibleIssueMarkers(entry, activeIssueTag)
  const isActive = entry.status === 'active'
  const summaryText = entrySummary(entry, `Running on ${entry.project_id}`)

  return (
    <div
      className={cn(
        'group relative rounded-xl border px-3.5 py-3 transition-all duration-200 cursor-pointer overflow-hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-950',
        selected
          ? 'border-sky-700/40 bg-sky-950/10 shadow-sm shadow-sky-900/10'
          : 'border-slate-800/30 bg-slate-900/15 hover:border-slate-700/50 hover:bg-slate-800/20',
      )}
      onClick={(e) => {
        e.stopPropagation()
        e.preventDefault()
        onToggle()
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          e.stopPropagation()
          onToggle()
        }
      }}
    >
      <div className="absolute left-0 top-0 bottom-0 w-[2px] rounded-full bg-sky-500/30" />
      <div className="flex items-center gap-2.5">
        <div
          className={cn(
            'rounded-md p-1',
            isActive ? 'bg-sky-500/10' : 'bg-slate-800/40',
          )}
        >
          <Bot
            className={cn(
              'h-3.5 w-3.5 flex-shrink-0',
              isActive ? 'text-sky-400' : 'text-sky-500/40',
            )}
          />
        </div>
        <span className="text-xs font-semibold text-slate-300 tracking-wide truncate">
          {entry.agent_slug || 'Agent'}
        </span>
        <span className="text-[10px] text-slate-600">
          on {entry.project_id}
        </span>
        {entry.external_id && (
          <span className="rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400/80">
            {entry.external_id}
          </span>
        )}
        <div className="flex-1" />
        <span
          className={cn(
            'rounded-md px-2 py-0.5 text-[10px] font-medium',
            entryStatusClasses(entry.status),
          )}
        >
          {entry.status}
        </span>
        {isActive && (
          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse shadow-[0_0_6px_theme(colors.emerald.400)]" />
        )}
        {entry.tool_count > 0 && (
          <span className="inline-flex items-center gap-1 rounded-md bg-slate-800/50 px-1.5 py-0.5 text-[10px] text-slate-500">
            <Wrench className="h-2.5 w-2.5" />
            {entry.tool_count}
          </span>
        )}
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 text-slate-600 transition-transform duration-200',
            !expanded && '-rotate-90',
          )}
        />
      </div>
      <p
        className={cn(
          'mt-1.5 text-xs text-slate-400/90 leading-relaxed',
          expanded ? 'whitespace-pre-wrap' : 'line-clamp-2',
        )}
      >
        {summaryText}
      </p>
      {issueMarkers[0] && !expanded && (
        <EntryIssueSummary issueMarkers={issueMarkers} />
      )}
      {expanded && details && !details.loading && !details.error && (
        <SessionTranscript
          events={details.events}
          narrationTags={narrationTags}
          narrationLoading={narrationLoading}
          issueMarkers={issueMarkers}
          personaName={entry.agent_slug || personaName}
          summaryText={summaryText}
          hideRedundantSummaryMessage
        />
      )}
      {expanded && details?.loading && <TranscriptLoading />}
      {expanded && details?.error && (
        <TranscriptError message={details.error} />
      )}
    </div>
  )
}

// ─── HeartbeatCard (compact) ───

export function HeartbeatCard({
  entry,
  activeIssueTag,
  selected,
  expanded,
  onToggle,
  details,
  narrationTags,
  narrationLoading,
  personaName,
}: CardProps) {
  const issueMarkers = visibleIssueMarkers(entry, activeIssueTag)
  const isActive = entry.status === 'active'
  const speakerName = getPersonaDisplayName(personaName)
  const summaryText = entrySummary(entry, 'Routine check completed')

  return (
    <div
      className={cn(
        'group relative rounded-xl border px-3.5 py-3 transition-all duration-200 cursor-pointer overflow-hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/40 focus-visible:ring-offset-1 focus-visible:ring-offset-slate-950',
        selected
          ? 'border-amber-700/40 bg-amber-950/10 shadow-sm shadow-amber-900/10'
          : 'border-slate-800/30 bg-slate-900/15 hover:border-slate-700/50 hover:bg-slate-800/20',
      )}
      onClick={(e) => {
        e.stopPropagation()
        e.preventDefault()
        onToggle()
      }}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          e.stopPropagation()
          onToggle()
        }
      }}
    >
      <div className="absolute left-0 top-0 bottom-0 w-[2px] rounded-full bg-amber-500/30" />
      <div className="flex items-center gap-2.5">
        <div
          className={cn(
            'rounded-md p-1',
            isActive ? 'bg-amber-500/10' : 'bg-slate-800/40',
          )}
        >
          <HeartPulse
            className={cn(
              'h-3.5 w-3.5',
              isActive ? 'text-amber-400 animate-pulse' : 'text-amber-500/40',
            )}
          />
        </div>
        <span className="text-xs font-semibold text-slate-300 tracking-wide">
          Heartbeat
        </span>
        {entry.external_id && (
          <span className="rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400/80">
            {entry.external_id}
          </span>
        )}
        <div className="flex-1" />
        <span
          className={cn(
            'rounded-md px-2 py-0.5 text-[10px] font-medium',
            entryStatusClasses(entry.status),
          )}
        >
          {entry.status}
        </span>
        {isActive && (
          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse shadow-[0_0_6px_theme(colors.emerald.400)]" />
        )}
        {entry.tool_count > 0 && (
          <span className="inline-flex items-center gap-1 rounded-md bg-slate-800/50 px-1.5 py-0.5 text-[10px] text-slate-500">
            <Wrench className="h-2.5 w-2.5" />
            {entry.tool_count}
          </span>
        )}
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 text-slate-600 transition-transform duration-200',
            !expanded && '-rotate-90',
          )}
        />
      </div>
      <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed">
        <span className="font-medium text-slate-300">{speakerName}:</span>{' '}
        <span className="text-slate-400/90">{summaryText}</span>
      </p>
      {issueMarkers[0] && !expanded && (
        <EntryIssueSummary issueMarkers={issueMarkers} />
      )}
      {expanded && details && !details.loading && !details.error && (
        <SessionTranscript
          events={details.events}
          narrationTags={narrationTags}
          narrationLoading={narrationLoading}
          issueMarkers={issueMarkers}
          personaName={personaName}
          summaryText={summaryText}
          hideRedundantSummaryMessage
        />
      )}
      {expanded && details?.loading && <TranscriptLoading />}
      {expanded && details?.error && (
        <TranscriptError message={details.error} />
      )}
    </div>
  )
}
