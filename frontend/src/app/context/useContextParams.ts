'use client'

import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useMemo } from 'react'
import { CONTEXT_DAYS, type ContextDays } from '@/lib/api/context-observability'

export interface ContextParams {
  days: ContextDays
  harness: string | null
  role: string | null
}

/** Page state lives in the URL so a view can be linked (an alert's "open" link included). */
export function useContextParams(defaults: {
  days: ContextDays
  harness?: string | null
  role?: string | null
}) {
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const key = params.toString()

  const state = useMemo<ContextParams>(() => {
    const p = new URLSearchParams(key)
    const days = Number(p.get('days')) as ContextDays
    return {
      days: CONTEXT_DAYS.includes(days) ? days : defaults.days,
      harness: p.get('harness') || defaults.harness || null,
      role: p.get('role') || defaults.role || null,
    }
  }, [key, defaults.days, defaults.harness, defaults.role])

  const update = useCallback(
    (patch: Partial<ContextParams>) => {
      const next = { ...state, ...patch }
      const p = new URLSearchParams()
      if (next.days !== defaults.days) p.set('days', String(next.days))
      // An explicit "all" (null) is kept out of the URL; a page default is written so a link is exact.
      if (next.harness) p.set('harness', next.harness)
      if (next.role) p.set('role', next.role)
      const query = p.toString()
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      })
    },
    [state, router, pathname, defaults.days],
  )

  return { state, update }
}
