import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import {
  fetchSession,
  fetchSessionEvents,
  querySessions,
} from '@/lib/api/sessions'

const PREVIEW_REFRESH_MS = 10_000
const PREVIEW_EVENT_LIMIT = 20
const SUBAGENT_PAGE_SIZE = 50
/** Bookkeeping events that would crowd out the messages a person scans for. */
export const PREVIEW_EXCLUDED_EVENT_TYPES = [
  'child_session_update',
  'usage_counter',
  'usage',
] as const

function isLive(status: string | undefined): boolean {
  return status === 'active' || status === 'running'
}

export function useSessionPreview(sessionId: string | null) {
  const enabled = Boolean(sessionId)

  const session = useQuery({
    queryKey: ['sessions', 'preview', sessionId, 'detail'],
    queryFn: () => fetchSession(sessionId as string, { includeEvents: false }),
    enabled,
    refetchInterval: (query) =>
      isLive(query.state.data?.status) ? PREVIEW_REFRESH_MS : false,
    refetchIntervalInBackground: false,
  })

  const live = isLive(session.data?.status)

  const events = useQuery({
    queryKey: ['sessions', 'preview', sessionId, 'events'],
    queryFn: () =>
      fetchSessionEvents(sessionId as string, {
        order: 'desc',
        page_size: PREVIEW_EVENT_LIMIT,
        exclude_types: PREVIEW_EXCLUDED_EVENT_TYPES,
      }),
    enabled,
    refetchInterval: live ? PREVIEW_REFRESH_MS : false,
    refetchIntervalInBackground: false,
  })

  const childCount = session.data?.child_session_count ?? 0
  const subagents = useQuery({
    queryKey: ['sessions', 'preview', sessionId, 'subagents'],
    queryFn: () =>
      querySessions({
        parent_session_id: sessionId as string,
        sort_by: 'last_active',
        sort_direction: 'desc',
        page_size: SUBAGENT_PAGE_SIZE,
      }),
    enabled: enabled && childCount > 0,
    refetchInterval: live ? PREVIEW_REFRESH_MS : false,
    refetchIntervalInBackground: false,
  })

  // The server returns newest first; the timeline reads oldest to newest.
  const latestEvents = useMemo(
    () => [...(events.data?.events ?? [])].reverse(),
    [events.data],
  )

  return {
    session: session.data ?? null,
    sessionError: session.error,
    isLoadingSession: session.isLoading,
    latestEvents,
    eventsTotal: events.data?.total ?? null,
    eventsError: events.error,
    isLoadingEvents: events.isLoading,
    subagents: subagents.data?.sessions ?? [],
    subagentsTotal: subagents.data?.total ?? 0,
    subagentsError: subagents.error,
    isLoadingSubagents: subagents.isLoading && childCount > 0,
    refetchSession: session.refetch,
  }
}
