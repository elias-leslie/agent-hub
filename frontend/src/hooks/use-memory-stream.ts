'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { getSseBaseUrl } from '@/lib/api-config'

export interface CaptureStreamEvent {
  id: string
  event_type: string
  timestamp: string
  data: {
    uuid: string
    title: string
    content: string
    source: string
    type: string
    session_id: string | null
    stored: boolean
  }
}

const MAX_EVENTS = 1000

interface UseMemoryStreamReturn {
  events: CaptureStreamEvent[]
  isConnected: boolean
  isPaused: boolean
  pause: () => void
  resume: () => void
  clear: () => void
}

export function useMemoryStream(): UseMemoryStreamReturn {
  const [events, setEvents] = useState<CaptureStreamEvent[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [isPaused, setIsPaused] = useState(false)

  const eventSourceRef = useRef<EventSource | null>(null)
  const retryDelayRef = useRef(1000)
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isPausedRef = useRef(false)
  const idCounterRef = useRef(0)

  isPausedRef.current = isPaused

  const connect = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }

    const baseUrl = getSseBaseUrl()
    const url = `${baseUrl}/api/memory/capture/stream`

    const es = new EventSource(url)
    eventSourceRef.current = es

    es.addEventListener('connected', () => {
      setIsConnected(true)
      retryDelayRef.current = 1000
    })

    es.addEventListener('observation', (e: MessageEvent) => {
      if (eventSourceRef.current !== es) return
      try {
        const parsed = JSON.parse(e.data)
        const streamEvent: CaptureStreamEvent = {
          id: `capture-${Date.now()}-${++idCounterRef.current}`,
          event_type: parsed.event_type,
          timestamp: parsed.timestamp,
          data: parsed.data,
        }
        setEvents((prev) => {
          const next = [streamEvent, ...prev]
          return next.length > MAX_EVENTS ? next.slice(0, MAX_EVENTS) : next
        })
      } catch {
        // Ignore parse errors
      }
    })

    es.addEventListener('heartbeat', () => {
      // Heartbeat received, connection is alive
    })

    es.onerror = () => {
      if (eventSourceRef.current !== es) return
      setIsConnected(false)
      es.close()
      eventSourceRef.current = null

      if (isPausedRef.current) return

      const delay = retryDelayRef.current
      retryDelayRef.current = Math.min(delay * 2, 30000)
      retryTimerRef.current = setTimeout(() => {
        if (!isPausedRef.current) {
          connect()
        }
      }, delay)
    }
  }, [])

  const disconnect = useCallback(() => {
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current)
      retryTimerRef.current = null
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
    setIsConnected(false)
  }, [])

  const pause = useCallback(() => {
    setIsPaused(true)
    isPausedRef.current = true
    disconnect()
  }, [disconnect])

  const resume = useCallback(() => {
    setIsPaused(false)
    isPausedRef.current = false
    retryDelayRef.current = 1000
    connect()
  }, [connect])

  const clear = useCallback(() => {
    setEvents([])
  }, [])

  useEffect(() => {
    if (!isPausedRef.current) {
      connect()
    }
    return () => {
      disconnect()
    }
  }, [connect, disconnect])

  return {
    events,
    isConnected,
    isPaused,
    pause,
    resume,
    clear,
  }
}
