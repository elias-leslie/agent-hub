'use client'

import { useCallback, useRef, useState } from 'react'
import { fetchApi, getApiBaseUrl } from '@/lib/api-config'

export interface NarrationTag {
  id: number
  task_id: string
  session_id: string
  tag_type: string
  content: string
  created_at: string
}

interface NarrationState {
  tags: NarrationTag[]
  loading: boolean
  error: string | null
}

/**
 * Fetch narration tags for a task on demand.
 * Returns a cache keyed by task_id so repeated expansions don't re-fetch.
 */
export function useNarrationTags() {
  const [cache, setCache] = useState<Record<string, NarrationState>>({})
  const inflightRef = useRef<Set<string>>(new Set())

  const fetchTags = useCallback(
    async (taskId: string) => {
      if (!taskId || inflightRef.current.has(taskId)) return
      const existing = cache[taskId]
      if (existing && !existing.error && existing.tags.length > 0) return

      inflightRef.current.add(taskId)
      setCache((prev) => ({
        ...prev,
        [taskId]: {
          tags: prev[taskId]?.tags ?? [],
          loading: true,
          error: null,
        },
      }))

      try {
        const response = await fetchApi(
          `${getApiBaseUrl()}/api/narration/tasks/${encodeURIComponent(taskId)}?limit=100`,
        )
        if (!response.ok) {
          throw new Error(`Failed to fetch narration tags: ${response.status}`)
        }
        const data = await response.json()
        setCache((prev) => ({
          ...prev,
          [taskId]: { tags: data.tags ?? [], loading: false, error: null },
        }))
      } catch (err) {
        setCache((prev) => ({
          ...prev,
          [taskId]: {
            tags: prev[taskId]?.tags ?? [],
            loading: false,
            error: err instanceof Error ? err.message : 'Failed to load',
          },
        }))
      } finally {
        inflightRef.current.delete(taskId)
      }
    },
    [cache],
  )

  return { narrationCache: cache, fetchNarrationTags: fetchTags }
}
