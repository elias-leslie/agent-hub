'use client'

import type { ChatMessage } from '@agent-hub/chat-ui'
import { useEffect, useMemo, useState } from 'react'
import type {
  PersonaStreamEntry,
  PersonaStreamMatch,
} from '@/lib/api/persona-stream'
import type { FilterMode } from './pulse-helpers'
import { entryHasPulseTag } from './pulse-helpers'

interface UseWorkspaceSearchOptions {
  deferredSearch: string
  searchMatches: PersonaStreamMatch[]
  matchCount: number
  hydratedEntries: PersonaStreamEntry[]
  messages: ChatMessage[]
}

type FilterCounts = Record<FilterMode, number>

export function useWorkspaceSearch({
  deferredSearch,
  searchMatches,
  matchCount,
  hydratedEntries,
  messages,
}: UseWorkspaceSearchOptions) {
  const [activeSearchMatchId, setActiveSearchMatchId] = useState<string | null>(
    null,
  )

  useEffect(() => {
    if (!deferredSearch.trim()) {
      setActiveSearchMatchId(null)
      return
    }
    if (searchMatches.length === 0) return
    const stillValid = searchMatches.some(
      (item) => item.entry_id === activeSearchMatchId,
    )
    if (!activeSearchMatchId || !stillValid) {
      setActiveSearchMatchId(searchMatches[0]?.entry_id ?? null)
    }
  }, [deferredSearch, searchMatches, activeSearchMatchId])

  const activeSearchMatch = useMemo(
    () =>
      searchMatches.findIndex((item) => item.entry_id === activeSearchMatchId),
    [activeSearchMatchId, searchMatches],
  )

  const activeMatchId = useMemo(() => {
    if (!deferredSearch.trim()) return null
    if (
      activeSearchMatchId &&
      searchMatches.some((item) => item.entry_id === activeSearchMatchId)
    ) {
      return activeSearchMatchId
    }
    return searchMatches[0]?.entry_id ?? null
  }, [deferredSearch, activeSearchMatchId, searchMatches])

  const matchedIds = useMemo(
    () => new Set(searchMatches.map((item) => item.entry_id)),
    [searchMatches],
  )

  const visibleSearchMatches = useMemo(() => {
    if (searchMatches.length === 0) return []
    if (activeSearchMatch < 0) return searchMatches.slice(0, 5)
    const start = Math.max(activeSearchMatch - 2, 0)
    const end = Math.min(start + 5, searchMatches.length)
    return searchMatches.slice(Math.max(end - 5, 0), end)
  }, [searchMatches, activeSearchMatch])

  const filterCounts = useMemo<FilterCounts>(() => {
    const messageEntries = hydratedEntries.filter(
      (e) => e.entry_type === 'message',
    )
    return {
      all: hydratedEntries.length + messages.length,
      messages: messageEntries.length + messages.length,
      work: hydratedEntries.filter(
        (e) => e.entry_type === 'heartbeat' || e.entry_type === 'child_run',
      ).length,
      heartbeats: hydratedEntries.filter((e) => e.entry_type === 'heartbeat')
        .length,
      friction: hydratedEntries.filter((e) => entryHasPulseTag(e, 'friction'))
        .length,
      errors: hydratedEntries.filter((e) => entryHasPulseTag(e, 'error'))
        .length,
      warnings: hydratedEntries.filter((e) => entryHasPulseTag(e, 'warning'))
        .length,
      stalled: hydratedEntries.filter((e) => entryHasPulseTag(e, 'stalled'))
        .length,
      drift: hydratedEntries.filter((e) =>
        entryHasPulseTag(e, 'instruction_drift'),
      ).length,
      tool_friction: hydratedEntries.filter((e) =>
        entryHasPulseTag(e, 'tool_friction'),
      ).length,
      retries: hydratedEntries.filter((e) => entryHasPulseTag(e, 'retries'))
        .length,
      recovered: hydratedEntries.filter((e) => entryHasPulseTag(e, 'recovered'))
        .length,
      escalations: hydratedEntries.filter((e) =>
        entryHasPulseTag(e, 'escalation'),
      ).length,
    }
  }, [hydratedEntries, messages])

  return {
    activeSearchMatchId,
    setActiveSearchMatchId,
    activeSearchMatch,
    activeMatchId,
    matchedIds,
    visibleSearchMatches,
    filterCounts,
    matchCount,
  }
}
