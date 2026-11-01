import { useEffect, useState } from 'react'

/** The current time, refreshed on an interval, so "loaded 2m ago" ages on screen while nothing else changes. */
export function useNow(everyMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), everyMs)
    return () => clearInterval(id)
  }, [everyMs])
  return now
}
