'use client'

import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useMemo } from 'react'
import type { SpendKind, SpendRange } from '@/lib/api/analytics'

export const RANGES: SpendRange[] = ['1h', '24h', '7d', '30d']
const KINDS: SpendKind[] = ['interactive', 'routine', 'other']

export interface CostsState {
  range: SpendRange
  kind: SpendKind | null
  project: string | null
  model: string | null
  /** Start of the chart bar the page is narrowed to. */
  bucket: string | null
  /** Ranked row whose drill-in is open. */
  item: string | null
}

type Patch = Partial<CostsState>

/** Page state lives in the URL so a drill-in (and a spend alert's link) can be opened directly. */
export function useCostsState() {
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const key = params.toString()

  const state = useMemo<CostsState>(() => {
    const p = new URLSearchParams(key)
    const range = p.get('range') as SpendRange | null
    const kind = p.get('kind') as SpendKind | null
    return {
      range: range && RANGES.includes(range) ? range : '24h',
      kind: kind && KINDS.includes(kind) ? kind : null,
      project: p.get('project') || null,
      model: p.get('model') || null,
      bucket: p.get('bucket') || null,
      item: p.get('item') || null,
    }
  }, [key])

  const update = useCallback(
    (patch: Patch) => {
      const next = { ...state, ...patch }
      // A bar belongs to one range's buckets; drop it when the range changes.
      if (patch.range && patch.range !== state.range) next.bucket = null
      const p = new URLSearchParams()
      if (next.range !== '24h') p.set('range', next.range)
      for (const name of [
        'kind',
        'project',
        'model',
        'bucket',
        'item',
      ] as const) {
        const value = next[name]
        if (value) p.set(name, value)
      }
      const query = p.toString()
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      })
    },
    [state, router, pathname],
  )

  return { state, update }
}
