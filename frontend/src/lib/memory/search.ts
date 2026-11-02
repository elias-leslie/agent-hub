/**
 * Search API operations.
 * Handles search and stats.
 */

import { getApiBaseUrl } from '../api-config'
import type {
  MemoryCategory,
  MemoryListResult,
  MemoryStats,
} from '../memory-types'
import { apiFetch, buildHeaders } from '../memory-utils'

const API_BASE = `${getApiBaseUrl()}/api`

// Fetch memory stats
export async function fetchMemoryStats(
  groupId?: string,
  allGroups: boolean = true,
): Promise<MemoryStats> {
  const params = new URLSearchParams()
  if (allGroups) params.set('all_groups', 'true')
  const qs = params.toString()
  const url = `${API_BASE}/memory/stats${qs ? `?${qs}` : ''}`

  return apiFetch(
    url,
    { headers: buildHeaders(groupId) },
    'Memory stats fetch failed',
  )
}

// Text search memories (for UI - simple substring search)
export async function searchMemories(
  query: string,
  params?: {
    limit?: number
    category?: MemoryCategory
    groupId?: string
  },
): Promise<MemoryListResult> {
  const searchParams = new URLSearchParams()
  searchParams.set('query', query)
  if (params?.limit) searchParams.set('limit', params.limit.toString())
  if (params?.category) searchParams.set('category', params.category)

  return apiFetch(
    `${API_BASE}/memory/text-search?${searchParams}`,
    { headers: buildHeaders(params?.groupId) },
    'Memory search failed',
  )
}
