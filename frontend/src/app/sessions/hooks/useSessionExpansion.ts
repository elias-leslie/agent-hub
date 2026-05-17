import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchAllSessionEvents,
  fetchSession,
  type Session,
  type SessionEventsResponse,
} from '@/lib/api'

const EXPANDED_SESSION_REFRESH_MS = 5_000

export function useSessionExpansion() {
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(
    null,
  )
  const [expandedSessionData, setExpandedSessionData] =
    useState<Session | null>(null)
  const [expandedEventsData, setExpandedEventsData] =
    useState<SessionEventsResponse | null>(null)
  const [isLoadingDetails, setIsLoadingDetails] = useState(false)
  const requestSequenceRef = useRef(0)

  const loadExpansion = useCallback(
    async (sessionId: string, requestId: number, showLoading: boolean) => {
      if (showLoading) {
        setExpandedSessionData(null)
        setExpandedEventsData(null)
        setIsLoadingDetails(true)
      }

      try {
        const [sessionData, eventsData] = await Promise.all([
          fetchSession(sessionId),
          fetchAllSessionEvents(sessionId, { page_size: 500 }),
        ])

        if (requestSequenceRef.current !== requestId) {
          return
        }

        setExpandedSessionData(sessionData)
        setExpandedEventsData(eventsData)
      } catch {
        if (requestSequenceRef.current !== requestId) {
          return
        }

        setExpandedSessionData(null)
        setExpandedEventsData(null)
      } finally {
        if (requestSequenceRef.current === requestId && showLoading) {
          setIsLoadingDetails(false)
        }
      }
    },
    [],
  )

  const handleToggleExpand = async (sessionId: string) => {
    if (expandedSessionId === sessionId) {
      requestSequenceRef.current += 1
      setExpandedSessionId(null)
      setExpandedSessionData(null)
      setExpandedEventsData(null)
      setIsLoadingDetails(false)
      return
    }

    const requestId = requestSequenceRef.current + 1
    requestSequenceRef.current = requestId
    setExpandedSessionId(sessionId)

    await loadExpansion(sessionId, requestId, true)
  }

  const clearExpansion = () => {
    requestSequenceRef.current += 1
    setExpandedSessionId(null)
    setExpandedSessionData(null)
    setExpandedEventsData(null)
    setIsLoadingDetails(false)
  }

  useEffect(() => {
    if (!expandedSessionId || expandedSessionData?.status !== 'active') {
      return
    }

    const interval = setInterval(() => {
      void loadExpansion(expandedSessionId, requestSequenceRef.current, false)
    }, EXPANDED_SESSION_REFRESH_MS)

    return () => clearInterval(interval)
  }, [expandedSessionData?.status, expandedSessionId, loadExpansion])

  return {
    expandedSessionId,
    expandedSessionData,
    expandedEventsData,
    isLoadingDetails,
    handleToggleExpand,
    clearExpansion,
  }
}
