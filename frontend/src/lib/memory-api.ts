/**
 * Memory API client for Agent Hub.
 * Handles memory dashboard operations: list, search, delete, stats.
 */

import { getApiBaseUrl } from "./api-config";
import { buildHeaders, apiFetch } from "./memory-utils";
import type {
  MemoryCategory,
  MemoryScope,
  MemorySortBy,
  MemorySortOrder,
  MemoryStats,
  MemoryListResult,
  MemoryGroup,
  DeleteEpisodeResponse,
  BulkDeleteResponse,
  AddEpisodeRequest,
  AddEpisodeResponse,
  UpdateTierResponse,
  UpdateEpisodePropertiesRequest,
  UpdateEpisodePropertiesResponse,
  TimelineGroup,
  MemoryAnalytics,
  SessionSummary,
  ContinuityContext,
} from "./memory-types";

const API_BASE = `${getApiBaseUrl()}/api`;

// Re-export types for convenience
export * from "./memory-types";
export { exportMemoriesAsJson, downloadJson } from "./memory-utils";

// Fetch memory stats
export async function fetchMemoryStats(groupId?: string): Promise<MemoryStats> {
  return apiFetch(
    `${API_BASE}/memory/stats`,
    { headers: buildHeaders(groupId) },
    "Memory stats fetch failed",
  );
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

  const url = searchParams.toString()
    ? `${API_BASE}/memory/list?${searchParams}`
    : `${API_BASE}/memory/list`;

  return apiFetch(
    url,
    { headers: buildHeaders(params?.groupId) },
    "Memory list fetch failed",
  );
}

// Fetch available scopes (mapped to MemoryGroup for UI compatibility)
export async function fetchMemoryGroups(): Promise<MemoryGroup[]> {
  const scopes: { scope: MemoryScope; count: number }[] = await apiFetch(
    `${API_BASE}/memory/scopes`,
    {},
    "Memory scopes fetch failed",
  );
  return scopes.map(s => ({ group_id: s.scope, episode_count: s.count }));
}

// Text search memories (for UI - simple substring search)
export async function searchMemories(
  query: string,
  params?: {
    limit?: number;
    category?: MemoryCategory;
    groupId?: string;
  },
): Promise<MemoryListResult> {
  const searchParams = new URLSearchParams();
  searchParams.set("query", query);
  if (params?.limit) searchParams.set("limit", params.limit.toString());
  if (params?.category) searchParams.set("category", params.category);

  return apiFetch(
    `${API_BASE}/memory/text-search?${searchParams}`,
    { headers: buildHeaders(params?.groupId) },
    "Memory search failed",
  );
}

// Delete single episode
export async function deleteMemory(
  episodeId: string,
  groupId?: string,
): Promise<DeleteEpisodeResponse> {
  return apiFetch(
    `${API_BASE}/memory/episode/${episodeId}`,
    { method: "DELETE", headers: buildHeaders(groupId) },
    "Delete memory failed",
  );
}

// Bulk delete episodes
export async function bulkDeleteMemories(
  ids: string[],
  groupId?: string,
): Promise<BulkDeleteResponse> {
  return apiFetch(
    `${API_BASE}/memory/bulk-delete`,
    {
      method: "POST",
      headers: buildHeaders(groupId, "application/json"),
      body: JSON.stringify({ ids }),
    },
    "Bulk delete failed",
  );
}

// Add episode (for edit flow with preserve_stats_from)
export async function addEpisode(
  request: AddEpisodeRequest,
  groupId?: string,
): Promise<AddEpisodeResponse> {
  return apiFetch(
    `${API_BASE}/memory/add`,
    {
      method: "POST",
      headers: buildHeaders(groupId, "application/json"),
      body: JSON.stringify(request),
    },
    "Add episode failed",
  );
}

// Update episode tier (category) - uses batch-update endpoint
export async function updateEpisodeTier(
  episodeId: string,
  tier: MemoryCategory,
): Promise<UpdateTierResponse> {
  const result = await apiFetch<{ results?: Array<{ success?: boolean; uuid?: string; error?: string }> }>(
    `${API_BASE}/memory/batch-update`,
    {
      method: "POST",
      headers: buildHeaders(undefined, "application/json"),
      body: JSON.stringify({
        updates: [{ uuid: episodeId, injection_tier: tier }],
      }),
    },
    "Update tier failed",
  );
  const firstResult = result.results?.[0];
  if (!firstResult?.success) {
    throw new Error(firstResult?.error || "Update tier failed");
  }
  return {
    success: true,
    episode_id: firstResult.uuid!,
    injection_tier: tier,
    message: `Tier updated to ${tier}`,
  };
}

// Update episode properties (pinned, auto_inject, display_order, trigger_task_types)
export async function updateEpisodeProperties(
  episodeId: string,
  properties: UpdateEpisodePropertiesRequest,
): Promise<UpdateEpisodePropertiesResponse> {
  return apiFetch(
    `${API_BASE}/memory/episode/${episodeId}/properties`,
    {
      method: "PATCH",
      headers: buildHeaders(undefined, "application/json"),
      body: JSON.stringify(properties),
    },
    "Update properties failed",
  );
}

export async function batchUpdateTier(
  ids: string[],
  tier: MemoryCategory,
): Promise<{ results: Array<{ success: boolean; uuid: string; error?: string }> }> {
  return apiFetch(
    `${API_BASE}/memory/batch-update`,
    {
      method: "POST",
      headers: buildHeaders(undefined, "application/json"),
      body: JSON.stringify({
        updates: ids.map((uuid) => ({ uuid, injection_tier: tier })),
      }),
    },
    "Batch tier update failed",
  );
}

export async function fetchTimeline(params?: {
  groupId?: string;
  scope?: MemoryScope;
  category?: MemoryCategory;
  limit?: number;
}): Promise<TimelineGroup[]> {
  const searchParams = new URLSearchParams();
  if (params?.groupId) searchParams.set("group_id", params.groupId);
  if (params?.scope) searchParams.set("scope", params.scope);
  if (params?.category) searchParams.set("category", params.category);
  if (params?.limit) searchParams.set("limit", params.limit.toString());

  const url = searchParams.toString()
    ? `${API_BASE}/memory/timeline?${searchParams}`
    : `${API_BASE}/memory/timeline`;

  return apiFetch(url, {}, "Timeline fetch failed");
}

export async function fetchMemoryAnalytics(params?: {
  groupId?: string;
  days?: number;
}): Promise<MemoryAnalytics> {
  const searchParams = new URLSearchParams();
  if (params?.groupId) searchParams.set("group_id", params.groupId);
  if (params?.days) searchParams.set("days", params.days.toString());

  const url = searchParams.toString()
    ? `${API_BASE}/memory/analytics?${searchParams}`
    : `${API_BASE}/memory/analytics`;

  return apiFetch(url, {}, "Memory analytics fetch failed");
}

export async function generateSessionSummary(
  sessionId: string,
): Promise<SessionSummary> {
  return apiFetch(
    `${API_BASE}/memory/sessions/${sessionId}/summarize`,
    { method: "POST" },
    "Session summary generation failed",
  );
}

export async function fetchEpisodeCitations(
  episodeId: string,
  limit?: number,
): Promise<import("./memory-types").EpisodeCitationsResponse> {
  const params = new URLSearchParams();
  if (limit) params.set("limit", limit.toString());
  const qs = params.toString();
  return apiFetch(
    `${API_BASE}/memory/episode/${episodeId}/citations${qs ? `?${qs}` : ""}`,
    {},
    "Citations fetch failed",
  );
}

export async function fetchSimilarEpisodes(
  episodeId: string,
  minScore?: number,
): Promise<import("./memory-types").SimilarEpisodesResponse> {
  const params = new URLSearchParams();
  if (minScore) params.set("min_score", minScore.toString());
  const qs = params.toString();
  return apiFetch(
    `${API_BASE}/memory/episode/${episodeId}/similar${qs ? `?${qs}` : ""}`,
    {},
    "Similar episodes fetch failed",
  );
}

export async function rateEpisode(
  uuid: string,
  rating: "helpful" | "harmful",
): Promise<{ success: boolean; uuid: string; rating: string; message: string }> {
  return apiFetch(
    `${API_BASE}/memory/episodes/${uuid}/rating`,
    {
      method: "POST",
      headers: buildHeaders(undefined, "application/json"),
      body: JSON.stringify({ rating }),
    },
    "Rate episode failed",
  );
}

export async function fetchContinuityContext(params?: {
  projectId?: string;
  days?: number;
  maxSessions?: number;
}): Promise<ContinuityContext> {
  const searchParams = new URLSearchParams();
  if (params?.projectId) searchParams.set("project_id", params.projectId);
  if (params?.days) searchParams.set("days", params.days.toString());
  if (params?.maxSessions) searchParams.set("max_sessions", params.maxSessions.toString());

  const qs = searchParams.toString();
  const url = `${API_BASE}/memory/continuity${qs ? `?${qs}` : ""}`;
  return apiFetch(url, {}, "Continuity context fetch failed");
}

export async function fetchEntities(params: {
  groupId: string;
  search?: string;
  limit?: number;
  offset?: number;
}): Promise<import("./memory-types").EntityListResult> {
  const searchParams = new URLSearchParams();
  searchParams.set("group_id", params.groupId);
  if (params.search) searchParams.set("search", params.search);
  if (params.limit) searchParams.set("limit", params.limit.toString());
  if (params.offset) searchParams.set("offset", params.offset.toString());
  return apiFetch(
    `${API_BASE}/memory/entities?${searchParams}`,
    {},
    "Entity list fetch failed",
  );
}

export async function fetchEntityHealth(
  groupId: string,
): Promise<import("./memory-types").EntityHealthSummary> {
  return apiFetch(
    `${API_BASE}/memory/entities/health?group_id=${encodeURIComponent(groupId)}`,
    {},
    "Entity health fetch failed",
  );
}

export async function fetchEntityEpisodes(
  entityName: string,
  groupId: string,
  limit?: number,
): Promise<import("./memory-types").EntityEpisode[]> {
  const params = new URLSearchParams();
  params.set("group_id", groupId);
  if (limit) params.set("limit", limit.toString());
  return apiFetch(
    `${API_BASE}/memory/entities/${encodeURIComponent(entityName)}/episodes?${params}`,
    {},
    "Entity episodes fetch failed",
  );
}

export async function cleanupOrphanedEdges(): Promise<{ edges_cleaned: number; edges_deleted: number }> {
  return apiFetch(
    `${API_BASE}/memory/cleanup-orphaned`,
    { method: "POST" },
    "Orphaned cleanup failed",
  );
}
