import { useCallback, useEffect, useRef, useState } from 'react'
import { useToastActions } from '@/components/error/toast'
import {
  fetchHeartbeatStatus,
  HeartbeatConflictError,
  type HeartbeatStatusResponse,
  triggerHeartbeat,
} from '@/lib/api/dashboard'

const IDLE_POLL_MS = 30_000
const RUNNING_POLL_MS = 10_000

export interface UseHeartbeatReturn {
  status: HeartbeatStatusResponse | null
  trigger: () => Promise<string | null>
  isTriggering: boolean
}

export function useHeartbeat(): UseHeartbeatReturn {
  const [status, setStatus] = useState<HeartbeatStatusResponse | null>(null)
  const [isTriggering, setIsTriggering] = useState(false)
  const toast = useToastActions()
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const prevRunningRef = useRef<boolean | undefined>(undefined)

  const poll = useCallback(async () => {
    try {
      const data = await fetchHeartbeatStatus()
      setStatus(data)
    } catch {
      // Silently ignore polling errors
    }
  }, [])

  // Set up polling with adaptive interval
  useEffect(() => {
    poll()

    const startPolling = (ms: number) => {
      if (intervalRef.current) clearInterval(intervalRef.current)
      intervalRef.current = setInterval(poll, ms)
    }

    // Only restart the interval when the running state actually transitions
    const currentRunning = status?.running ?? false
    if (prevRunningRef.current !== currentRunning) {
      startPolling(currentRunning ? RUNNING_POLL_MS : IDLE_POLL_MS)
      prevRunningRef.current = currentRunning
    } else if (intervalRef.current === null) {
      // Ensure interval is started on mount even if status is null
      startPolling(IDLE_POLL_MS)
    }

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [poll, status?.running])

  const trigger = useCallback(async () => {
    setIsTriggering(true)
    try {
      const response = await triggerHeartbeat()
      toast.success('Heartbeat triggered')
      // Immediately refresh status
      await poll()
      return response.session_id
    } catch (err) {
      if (err instanceof HeartbeatConflictError) {
        toast.warning('Heartbeat already in progress')
        await poll()
        return err.runningSessionId
      } else {
        toast.error(
          'Failed to trigger heartbeat',
          err instanceof Error ? err.message : undefined,
        )
      }
      return null
    } finally {
      setIsTriggering(false)
    }
  }, [toast, poll])

  return { status, trigger, isTriggering }
}
