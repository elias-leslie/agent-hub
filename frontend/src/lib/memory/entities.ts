/**
 * Entity-related API operations.
 * Handles entity listing, health checks, and entity episode relationships.
 */

import { getApiBaseUrl } from "../api-config";
import { apiFetch } from "../memory-utils";
import type {
  EntityListResult,
  EntityHealthSummary,
  EntityEpisode,
} from "../memory-types";

const API_BASE = `${getApiBaseUrl()}/api`;

// Fetch entities with optional search and pagination
export async function fetchEntities(params: {
  groupId: string;
  search?: string;
  limit?: number;
  offset?: number;
}): Promise<EntityListResult> {
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

// Fetch entity health summary (orphans, duplicates)
export async function fetchEntityHealth(
  groupId: string,
): Promise<EntityHealthSummary> {
  return apiFetch(
    `${API_BASE}/memory/entities/health?group_id=${encodeURIComponent(groupId)}`,
    {},
    "Entity health fetch failed",
  );
}

// Fetch episodes associated with an entity
export async function fetchEntityEpisodes(
  entityName: string,
  groupId: string,
  limit?: number,
): Promise<EntityEpisode[]> {
  const params = new URLSearchParams();
  params.set("group_id", groupId);
  if (limit) params.set("limit", limit.toString());
  return apiFetch(
    `${API_BASE}/memory/entities/${encodeURIComponent(entityName)}/episodes?${params}`,
    {},
    "Entity episodes fetch failed",
  );
}

// Run memory cleanup (orphaned edges, stale refs, duplicates)
export interface CleanupResult {
  edges_updated: number;
  edges_deleted: number;
  stale_refs_removed: number;
  entities_deleted: number;
  duplicates_merged: number;
}

export async function runMemoryCleanup(): Promise<CleanupResult> {
  return apiFetch(
    `${API_BASE}/memory/cleanup-orphaned`,
    { method: "POST" },
    "Memory cleanup failed",
  );
}
