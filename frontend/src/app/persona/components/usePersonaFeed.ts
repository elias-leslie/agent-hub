'use client'

import type { ChatMessage } from '@agent-hub/chat-ui'
import { startTransition, useEffect, useMemo, useState } from 'react'
import {
  fetchPersonaStream,
  type PersonaPulseSummary,
  type PersonaStreamEntry,
  type PersonaStreamEventPreview,
  type PersonaStreamMatch,
} from '@/lib/api/persona-stream'
import type { FilterMode } from './pulse-helpers'
import { entryHasPulseTag, filterModeToPulseTag } from './pulse-helpers'
import type { TimeRange } from './TimeRangeDropdown'
import { buildLocalFeedMessages, buildRemoteFeedItems } from './workspace-feed'
import type { FeedItem } from './workspace-types'
import {
  EMPTY_PULSE,
  type LiveSessionPatch,
  PAGE_SIZE,
} from './workspace-types'

export interface PersonaFeedOptions {
  timeRange: TimeRange
  deferredSearch: string
  focusSessionId: string | null
  anchorEntryId: string | null
  page: number
  currentSessionId: string | null
  activeSessionId: string | null
  sidebarRefreshTrigger: number
  liveRefreshTick: number
  runtimeSyncKey: string
  filterMode: FilterMode
  liveSessionPatches: Record<string, LiveSessionPatch>
  messages: ChatMessage[]
  personaDisplayName: string
}

function mergeEntries(
  prev: PersonaStreamEntry[],
  next: PersonaStreamEntry[],
): PersonaStreamEntry[] {
  if (prev.length === 0) return next
  const merged = [...prev]
  for (const entry of next) {
    if (!merged.some((existing) => existing.id === entry.id)) {
      merged.push(entry)
    }
  }
  return merged
}

function applyLivePatch(
  entry: PersonaStreamEntry,
  patch: LiveSessionPatch,
): PersonaStreamEntry {
  return {
    ...entry,
    live_summary: patch.liveSummary ?? entry.live_summary,
    live_status: patch.liveStatus ?? entry.live_status,
    status:
      patch.liveStatus === 'failed'
        ? 'failed'
        : patch.liveStatus === 'completed' && entry.status === 'active'
          ? 'completed'
          : entry.status,
    event_previews: mergeEventPreviewsInline(
      entry.event_previews,
      patch.eventPreviews,
    ),
  }
}

function mergeEventPreviewsInline(
  existing: PersonaStreamEventPreview[],
  updates: PersonaStreamEventPreview[],
): PersonaStreamEventPreview[] {
  if (updates.length === 0) return existing
  const merged = [...existing]
  for (const update of updates) {
    const index = merged.findIndex(
      (item) => item.tool_name === update.tool_name,
    )
    if (index >= 0) {
      merged[index] = update
    } else {
      merged.push(update)
    }
  }
  return merged
}

function filterFeedItems(
  items: FeedItem[],
  filterMode: FilterMode,
): FeedItem[] {
  if (filterMode === 'all') return items
  if (filterMode === 'messages')
    return items.filter((item) => item.kind === 'message')
  if (filterMode === 'heartbeats')
    return items.filter((item) => item.kind === 'heartbeat')
  if (filterMode === 'work')
    return items.filter(
      (item) => item.kind === 'child_run' || item.kind === 'heartbeat',
    )

  const pulseTag = filterModeToPulseTag(filterMode)
  if (!pulseTag) return items

  return items.filter((item) => {
    if (item.kind === 'message') {
      return pulseTag === 'error'
        ? /error|failed|warning|blocked/i.test(item.message.content)
        : false
    }
    return entryHasPulseTag(item.entry, pulseTag)
  })
}

export function usePersonaFeed({
  timeRange,
  deferredSearch,
  focusSessionId,
  anchorEntryId,
  page,
  currentSessionId,
  activeSessionId,
  sidebarRefreshTrigger,
  liveRefreshTick,
  runtimeSyncKey,
  filterMode,
  liveSessionPatches,
  messages,
  personaDisplayName,
}: PersonaFeedOptions) {
  const [entries, setEntries] = useState<PersonaStreamEntry[]>([])
  const [pulse, setPulse] = useState<PersonaPulseSummary>(EMPTY_PULSE)
  const [searchMatches, setSearchMatches] = useState<PersonaStreamMatch[]>([])
  const [matchCount, setMatchCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [total, setTotal] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    const effectiveRange = deferredSearch.trim() ? 'all' : timeRange
    fetchPersonaStream({
      timeRange: effectiveRange,
      search: deferredSearch.trim() || undefined,
      focusSessionId,
      anchorEntryId,
      page,
      pageSize: PAGE_SIZE,
    })
      .then((data) => {
        if (cancelled) return
        startTransition(() => {
          setEntries((prev) =>
            page === 1 ? data.entries : mergeEntries(prev, data.entries),
          )
          setTotal(data.total)
          setSearchMatches(data.matches)
          setMatchCount(data.match_count)
          setPulse(data.pulse ?? EMPTY_PULSE)
          setError(null)
          setLoading(false)
        })
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load stream')
        setPulse(EMPTY_PULSE)
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [
    timeRange,
    deferredSearch,
    focusSessionId,
    anchorEntryId,
    page,
    currentSessionId,
    sidebarRefreshTrigger,
    liveRefreshTick,
    runtimeSyncKey,
  ])

  const hydratedEntries = useMemo(
    () =>
      entries.map((entry) => {
        const patch = liveSessionPatches[entry.session_id]
        return patch ? applyLivePatch(entry, patch) : entry
      }),
    [entries, liveSessionPatches],
  )

  const mergedItems = useMemo(() => {
    const remote = buildRemoteFeedItems(
      [...hydratedEntries].reverse(),
      personaDisplayName,
    )
    const local = buildLocalFeedMessages(
      messages,
      currentSessionId || activeSessionId,
      personaDisplayName,
    )
    const allItems = [...remote, ...local].sort(
      (a, b) => a.timestamp.getTime() - b.timestamp.getTime(),
    )
    return filterFeedItems(allItems, filterMode)
  }, [
    hydratedEntries,
    messages,
    currentSessionId,
    activeSessionId,
    filterMode,
    personaDisplayName,
  ])

  const activeStreamSessionIds = useMemo(() => {
    const activeIds = new Set<string>()
    for (const entry of hydratedEntries) {
      if (entry.status === 'active' || entry.live_status === 'active') {
        activeIds.add(entry.session_id)
      }
    }
    return Array.from(activeIds)
  }, [hydratedEntries])

  const visiblePulseMetrics = useMemo(
    () =>
      pulse.metrics.filter(
        (metric) => metric.count > 0 || metric.key === 'friction',
      ),
    [pulse.metrics],
  )

  return {
    entries,
    pulse,
    visiblePulseMetrics,
    searchMatches,
    matchCount,
    loading,
    error,
    total,
    hydratedEntries,
    mergedItems,
    activeStreamSessionIds,
  }
}
