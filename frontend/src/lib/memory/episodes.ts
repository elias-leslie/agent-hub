/**
 * Episode-related API operations.
 * Handles CRUD, bulk operations, and episode management.
 */

import { getApiBaseUrl } from '../api-config'
import type {
  AddEpisodeRequest,
  AddEpisodeResponse,
  BulkDeleteResponse,
  DeleteEpisodeResponse,
  MemoryCategory,
  MemoryGroup,
  MemoryListResult,
  MemoryScope,
  MemorySortBy,
  MemorySortOrder,
  SimilarEpisodesResponse,
  UpdateEpisodePropertiesRequest,
  UpdateEpisodePropertiesResponse,
  UpdateTierResponse,
} from '../memory-types'
import { apiFetch, buildHeaders } from '../memory-utils'

const API_BASE = `${getApiBaseUrl()}/api`

// Fetch paginated memory list
export async function fetchMemoryList(params?: {
  limit?: number
  cursor?: string
  category?: MemoryCategory
  scope?: MemoryScope
  groupId?: string
  sortBy?: MemorySortBy
  sortOrder?: MemorySortOrder
  allGroups?: boolean
}): Promise<MemoryListResult> {
  const searchParams = new URLSearchParams()
  const allGroups = params?.allGroups ?? true
  if (params?.limit) searchParams.set('limit', params.limit.toString())
  if (params?.cursor) searchParams.set('cursor', params.cursor)
  if (params?.category) searchParams.set('category', params.category)
  if (params?.scope) searchParams.set('scope', params.scope)
  if (params?.sortBy) searchParams.set('sort_by', params.sortBy)
  if (params?.sortOrder) searchParams.set('sort_order', params.sortOrder)
  if (allGroups) searchParams.set('all_groups', 'true')

  const url = searchParams.toString()
    ? `${API_BASE}/memory/list?${searchParams}`
    : `${API_BASE}/memory/list`

  return apiFetch(
    url,
    { headers: buildHeaders(params?.groupId) },
    'Memory list fetch failed',
  )
}

// Fetch available scopes (mapped to MemoryGroup for UI compatibility)
export async function fetchMemoryGroups(): Promise<MemoryGroup[]> {
  const scopes: { scope: MemoryScope; count: number }[] = await apiFetch(
    `${API_BASE}/memory/scopes`,
    {},
    'Memory scopes fetch failed',
  )
  return scopes.map((s) => ({ group_id: s.scope, episode_count: s.count }))
}

// Delete single episode
export async function deleteMemory(
  episodeId: string,
  groupId?: string,
): Promise<DeleteEpisodeResponse> {
  return apiFetch(
    `${API_BASE}/memory/episode/${episodeId}`,
    { method: 'DELETE', headers: buildHeaders(groupId) },
    'Delete memory failed',
  )
}

// Bulk delete episodes
export async function bulkDeleteMemories(
  ids: string[],
  groupId?: string,
): Promise<BulkDeleteResponse> {
  return apiFetch(
    `${API_BASE}/memory/bulk-delete`,
    {
      method: 'POST',
      headers: buildHeaders(groupId, 'application/json'),
      body: JSON.stringify({ ids }),
    },
    'Bulk delete failed',
  )
}

// Add episode (for edit flow with preserve_stats_from)
export async function addEpisode(
  request: AddEpisodeRequest,
  groupId?: string,
): Promise<AddEpisodeResponse> {
  return apiFetch(
    `${API_BASE}/memory/add`,
    {
      method: 'POST',
      headers: buildHeaders(groupId, 'application/json'),
      body: JSON.stringify(request),
    },
    'Add episode failed',
  )
}

// Update episode tier (category) - uses batch-update endpoint
export async function updateEpisodeTier(
  episodeId: string,
  tier: MemoryCategory,
): Promise<UpdateTierResponse> {
  const result = await apiFetch<{
    results?: Array<{ success?: boolean; uuid?: string; error?: string }>
  }>(
    `${API_BASE}/memory/batch-update`,
    {
      method: 'POST',
      headers: buildHeaders(undefined, 'application/json'),
      body: JSON.stringify({
        updates: [{ uuid: episodeId, injection_tier: tier }],
      }),
    },
    'Update tier failed',
  )
  const firstResult = result.results?.[0]
  if (!firstResult?.success) {
    throw new Error(firstResult?.error || 'Update tier failed')
  }
  return {
    success: true,
    episode_id: firstResult.uuid!,
    injection_tier: tier,
    message: `Tier updated to ${tier}`,
  }
}

// Update episode properties (pinned, auto_inject, display_order, trigger_task_types)
export async function updateEpisodeProperties(
  episodeId: string,
  properties: UpdateEpisodePropertiesRequest,
): Promise<UpdateEpisodePropertiesResponse> {
  return apiFetch(
    `${API_BASE}/memory/episode/${episodeId}/properties`,
    {
      method: 'PATCH',
      headers: buildHeaders(undefined, 'application/json'),
      body: JSON.stringify(properties),
    },
    'Update properties failed',
  )
}

// Batch update tier for multiple episodes
export async function batchUpdateTier(
  ids: string[],
  tier: MemoryCategory,
): Promise<{
  results: Array<{ success: boolean; uuid: string; error?: string }>
}> {
  return apiFetch(
    `${API_BASE}/memory/batch-update`,
    {
      method: 'POST',
      headers: buildHeaders(undefined, 'application/json'),
      body: JSON.stringify({
        updates: ids.map((uuid) => ({ uuid, injection_tier: tier })),
      }),
    },
    'Batch tier update failed',
  )
}

// Fetch similar episodes
export async function fetchSimilarEpisodes(
  episodeId: string,
  minScore?: number,
): Promise<SimilarEpisodesResponse> {
  const params = new URLSearchParams()
  if (minScore) params.set('min_score', minScore.toString())
  const qs = params.toString()
  return apiFetch(
    `${API_BASE}/memory/episode/${episodeId}/similar${qs ? `?${qs}` : ''}`,
    {},
    'Similar episodes fetch failed',
  )
}
