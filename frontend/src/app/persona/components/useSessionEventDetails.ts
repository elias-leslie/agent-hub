'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchSessionEvents } from '@/lib/api/sessions'
import type { TimelineEvent } from '@/types/events'
import type { SessionEventDetailsState } from './workspace-types'

function sortEvents(events: TimelineEvent[]): TimelineEvent[] {
  return [...events].sort((left, right) => {
    const turnDiff = left.turn - right.turn
    if (turnDiff !== 0) return turnDiff
    const seqDiff = left.sequence - right.sequence
    if (seqDiff !== 0) return seqDiff
    return +new Date(left.created_at) - +new Date(right.created_at)
  })
}

async function fetchAllSessionEvents(
  sessionId: string,
): Promise<TimelineEvent[]> {
  const allEvents: TimelineEvent[] = []
  let pageNumber = 1
  let totalEvents = 0
  do {
    const response = await fetchSessionEvents(sessionId, {
      page: pageNumber,
      page_size: 500,
    })
    totalEvents = response.total
    allEvents.push(...response.events)
    pageNumber += 1
  } while (allEvents.length < totalEvents)
  return sortEvents(allEvents)
}

export function useSessionEventDetails() {
  const [sessionEventDetails, setSessionEventDetails] = useState<
    Record<string, SessionEventDetailsState>
  >({})
  const sessionEventDetailsRef = useRef<
    Record<string, SessionEventDetailsState>
  >({})

  useEffect(() => {
    sessionEventDetailsRef.current = sessionEventDetails
  }, [sessionEventDetails])

  const loadSessionEventDetails = useCallback(
    async (sessionId: string, force = false) => {
      const existing = sessionEventDetailsRef.current[sessionId]
      if (!force && existing?.loading) return
      if (!force && existing && existing.events.length > 0 && !existing.error)
        return

      setSessionEventDetails((current) => ({
        ...current,
        [sessionId]: {
          loading: true,
          error: null,
          events: current[sessionId]?.events ?? [],
        },
      }))

      try {
        const allEvents = await fetchAllSessionEvents(sessionId)
        setSessionEventDetails((current) => ({
          ...current,
          [sessionId]: { loading: false, error: null, events: allEvents },
        }))
      } catch (err) {
        setSessionEventDetails((current) => ({
          ...current,
          [sessionId]: {
            loading: false,
            error:
              err instanceof Error
                ? err.message
                : 'Failed to load full session detail',
            events: current[sessionId]?.events ?? [],
          },
        }))
      }
    },
    [],
  )

  return { sessionEventDetails, loadSessionEventDetails }
}
