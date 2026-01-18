/**
 * Memory API client for Agent Hub.
 * Handles memory dashboard operations: list, search, delete, stats.
 */

const API_BASE = "/api";

// Memory category types (matching backend)
export type MemoryCategory =
  | "session_insight"
  | "codebase_discovery"
  | "pattern"
  | "gotcha"
  | "task_outcome"
  | "qa_result"
  | "historical_context"
  | "uncategorized";

export type MemorySource = "chat" | "voice" | "system";

// Memory episode for display
export interface MemoryEpisode {
  uuid: string;
  name: string;
  content: string;
  source: MemorySource;
  category: MemoryCategory;
  source_description: string;
  created_at: string;
  valid_at: string;
  entities: string[];
}

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

// Memory stats for KPI cards
export interface MemoryStats {
  total: number;
  by_category: MemoryCategoryCount[];
  last_updated: string | null;
  group_id: string;
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

  const response = await fetch(`${API_BASE}/memory/stats`, { headers });
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
  groupId?: string;
}): Promise<MemoryListResult> {
  const searchParams = new URLSearchParams();
  if (params?.limit) searchParams.set("limit", params.limit.toString());
  if (params?.cursor) searchParams.set("cursor", params.cursor);
  if (params?.category) searchParams.set("category", params.category);

  const headers: HeadersInit = {};
  if (params?.groupId) {
    headers["x-group-id"] = params.groupId;
  }

  const url = searchParams.toString()
    ? `${API_BASE}/memory/list?${searchParams}`
    : `${API_BASE}/memory/list`;

  const response = await fetch(url, { headers });
  if (!response.ok) {
    throw new Error(`Memory list fetch failed: ${response.status}`);
  }
  return response.json();
}

// Fetch available groups
export async function fetchMemoryGroups(): Promise<MemoryGroup[]> {
  const response = await fetch(`${API_BASE}/memory/groups`);
  if (!response.ok) {
    throw new Error(`Memory groups fetch failed: ${response.status}`);
  }
  return response.json();
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

  const response = await fetch(
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

  const response = await fetch(`${API_BASE}/memory/episode/${episodeId}`, {
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

  const response = await fetch(`${API_BASE}/memory/bulk-delete`, {
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
