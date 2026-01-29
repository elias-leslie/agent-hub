/**
 * Memory API client for Agent Hub.
 * Handles memory dashboard operations: list, search, delete, stats.
 */

import { getApiBaseUrl, fetchApi } from "./api-config";

const API_BASE = `${getApiBaseUrl()}/api`;

// Memory scope types (matching backend MemoryScope enum)
export type MemoryScope = "global" | "project" | "task";

// Memory category types (tier-first taxonomy)
export type MemoryCategory = "mandate" | "guardrail" | "reference";

export type MemorySource = "chat" | "voice" | "system";

// Memory episode for display
export interface MemoryEpisode {
  uuid: string;
  name: string;
  content: string;
  source: MemorySource;
  category: MemoryCategory;
  scope: MemoryScope;
  scope_id: string | null;
  source_description: string;
  created_at: string;
  valid_at: string;
  entities: string[];
  // ACE-aligned usage stats
  loaded_count?: number;
  referenced_count?: number;
  helpful_count?: number;
  harmful_count?: number;
  utility_score?: number;
  // Context-aware injection
  trigger_task_types?: string[];
}

// Sort options for memory list
export type MemorySortBy = "created_at" | "utility_score" | "loaded_count";
export type MemorySortOrder = "asc" | "desc";

// Paginated list result
export interface MemoryListResult {
  episodes: MemoryEpisode[];
  total: number;
  cursor: string | null;
  has_more: boolean;
}

// Category count for stats
export interface MemoryCategoryCount {
  category: MemoryCategory;
  count: number;
}

// Scope count for stats
export interface MemoryScopeCount {
  scope: MemoryScope;
  count: number;
}

// Memory stats for KPI cards
export interface MemoryStats {
  total: number;
  by_category: MemoryCategoryCount[];
  by_scope: MemoryScopeCount[];
  last_updated: string | null;
  scope: MemoryScope;
  scope_id: string | null;
}

// Memory group
export interface MemoryGroup {
  group_id: string;
  episode_count: number;
}

// Search result (reusing episode structure)
export interface MemorySearchResult {
  uuid: string;
  content: string;
  source: MemorySource;
  relevance_score: number;
  created_at: string;
  facts: string[];
  scope?: MemoryScope;
  category?: MemoryCategory;
}

export interface SearchResponse {
  query: string;
  results: MemorySearchResult[];
  count: number;
}

// Delete responses
export interface DeleteEpisodeResponse {
  success: boolean;
  episode_id: string;
  message: string;
}

export interface BulkDeleteError {
  id: string;
  error: string;
}

export interface BulkDeleteResponse {
  deleted: number;
  failed: number;
  errors: BulkDeleteError[];
}

// Fetch memory stats
export async function fetchMemoryStats(
  groupId?: string,
): Promise<MemoryStats> {
  const headers: HeadersInit = {};
  if (groupId) {
    headers["x-group-id"] = groupId;
  }

  const response = await fetchApi(`${API_BASE}/memory/stats`, { headers });
  if (!response.ok) {
    throw new Error(`Memory stats fetch failed: ${response.status}`);
  }
  return response.json();
}

// Fetch paginated memory list
export async function fetchMemoryList(params?: {
  limit?: number;
  cursor?: string;
  category?: MemoryCategory;
  scope?: MemoryScope;
  groupId?: string;
  sortBy?: MemorySortBy;
  sortOrder?: MemorySortOrder;
}): Promise<MemoryListResult> {
  const searchParams = new URLSearchParams();
  if (params?.limit) searchParams.set("limit", params.limit.toString());
  if (params?.cursor) searchParams.set("cursor", params.cursor);
  if (params?.category) searchParams.set("category", params.category);
  if (params?.scope) searchParams.set("scope", params.scope);
  if (params?.sortBy) searchParams.set("sort_by", params.sortBy);
  if (params?.sortOrder) searchParams.set("sort_order", params.sortOrder);

  const headers: HeadersInit = {};
  if (params?.groupId) {
    headers["x-group-id"] = params.groupId;
  }

  const url = searchParams.toString()
    ? `${API_BASE}/memory/list?${searchParams}`
    : `${API_BASE}/memory/list`;

  const response = await fetchApi(url, { headers });
  if (!response.ok) {
    throw new Error(`Memory list fetch failed: ${response.status}`);
  }
  return response.json();
}

// Fetch available scopes (mapped to MemoryGroup for UI compatibility)
export async function fetchMemoryGroups(): Promise<MemoryGroup[]> {
  const response = await fetchApi(`${API_BASE}/memory/scopes`);
  if (!response.ok) {
    throw new Error(`Memory scopes fetch failed: ${response.status}`);
  }
  // Backend returns {scope, count}[], map to {group_id, episode_count}[]
  const scopes: { scope: MemoryScope; count: number }[] = await response.json();
  return scopes.map(s => ({ group_id: s.scope, episode_count: s.count }));
}

// Search memories
export async function searchMemories(
  query: string,
  params?: {
    limit?: number;
    minScore?: number;
    groupId?: string;
  },
): Promise<SearchResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set("query", query);
  if (params?.limit) searchParams.set("limit", params.limit.toString());
  if (params?.minScore)
    searchParams.set("min_score", params.minScore.toString());

  const headers: HeadersInit = {};
  if (params?.groupId) {
    headers["x-group-id"] = params.groupId;
  }

  const response = await fetchApi(
    `${API_BASE}/memory/search?${searchParams}`,
    { headers },
  );
  if (!response.ok) {
    throw new Error(`Memory search failed: ${response.status}`);
  }
  return response.json();
}

// Delete single episode
export async function deleteMemory(
  episodeId: string,
  groupId?: string,
): Promise<DeleteEpisodeResponse> {
  const headers: HeadersInit = {};
  if (groupId) {
    headers["x-group-id"] = groupId;
  }

  const response = await fetchApi(`${API_BASE}/memory/episode/${episodeId}`, {
    method: "DELETE",
    headers,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Delete memory failed: ${response.status}`);
  }
  return response.json();
}

// Bulk delete episodes
export async function bulkDeleteMemories(
  ids: string[],
  groupId?: string,
): Promise<BulkDeleteResponse> {
  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (groupId) {
    headers["x-group-id"] = groupId;
  }

  const response = await fetchApi(`${API_BASE}/memory/bulk-delete`, {
    method: "POST",
    headers,
    body: JSON.stringify({ ids }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      error.detail || `Bulk delete failed: ${response.status}`,
    );
  }
  return response.json();
}

// Add episode request/response
export interface AddEpisodeRequest {
  content: string;
  source?: MemorySource;
  source_description?: string;
  injection_tier?: MemoryCategory;
  preserve_stats_from?: string;
}

export interface AddEpisodeResponse {
  uuid: string;
  message: string;
}

// Add episode (for edit flow with preserve_stats_from)
export async function addEpisode(
  request: AddEpisodeRequest,
  groupId?: string,
): Promise<AddEpisodeResponse> {
  const headers: HeadersInit = {
    "Content-Type": "application/json",
  };
  if (groupId) {
    headers["x-group-id"] = groupId;
  }

  const response = await fetchApi(`${API_BASE}/memory/add`, {
    method: "POST",
    headers,
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Add episode failed: ${response.status}`);
  }
  return response.json();
}

// Update episode tier response
export interface UpdateTierResponse {
  success: boolean;
  episode_id: string;
  injection_tier: string;
  message: string;
}

// Update episode tier (category)
export async function updateEpisodeTier(
  episodeId: string,
  tier: MemoryCategory,
): Promise<UpdateTierResponse> {
  const response = await fetchApi(`${API_BASE}/memory/episode/${episodeId}/tier`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ injection_tier: tier }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Update tier failed: ${response.status}`);
  }
  return response.json();
}

// Update episode properties request
export interface UpdateEpisodePropertiesRequest {
  pinned?: boolean;
  auto_inject?: boolean;
  display_order?: number;
  trigger_task_types?: string[];
}

// Update episode properties response
export interface UpdateEpisodePropertiesResponse {
  success: boolean;
  episode_id: string;
  pinned?: boolean;
  auto_inject?: boolean;
  display_order?: number;
  trigger_task_types?: string[];
  message: string;
}

// Update episode properties (pinned, auto_inject, display_order, trigger_task_types)
export async function updateEpisodeProperties(
  episodeId: string,
  properties: UpdateEpisodePropertiesRequest,
): Promise<UpdateEpisodePropertiesResponse> {
  const response = await fetchApi(`${API_BASE}/memory/episode/${episodeId}/properties`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(properties),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Update properties failed: ${response.status}`);
  }
  return response.json();
}

// Export memories as JSON blob
export function exportMemoriesAsJson(episodes: MemoryEpisode[]): Blob {
  const data = {
    exported_at: new Date().toISOString(),
    count: episodes.length,
    episodes,
  };
  return new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
}

// Trigger download of JSON blob
export function downloadJson(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
