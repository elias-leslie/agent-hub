/**
 * Search and analytics API operations.
 * Handles search, timeline, analytics, continuity, stats, and session summaries.
 */

import { getApiBaseUrl } from "../api-config";
import { buildHeaders, apiFetch } from "../memory-utils";
import type {
  MemoryCategory,
  MemoryScope,
  MemoryListResult,
  MemoryStats,
  TimelineGroup,
  MemoryAnalytics,
  MetricsDashboard,
  TopMemory,
  TierChangesSummary,
  SessionSummary,
  ContinuityContext,
} from "../memory-types";

const API_BASE = `${getApiBaseUrl()}/api`;

// Fetch memory stats
export async function fetchMemoryStats(groupId?: string): Promise<MemoryStats> {
  return apiFetch(
    `${API_BASE}/memory/stats`,
    { headers: buildHeaders(groupId) },
    "Memory stats fetch failed",
  );
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

// Fetch timeline view of episodes
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

// Fetch memory analytics
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

// Fetch memory injection metrics (PostgreSQL)
export async function fetchMemoryMetrics(params?: {
  days?: number;
  period?: string;
}): Promise<MetricsDashboard> {
  const searchParams = new URLSearchParams();
  if (params?.days) searchParams.set("days", params.days.toString());
  if (params?.period) searchParams.set("period", params.period);

  const qs = searchParams.toString();
  const url = `${API_BASE}/memory/metrics${qs ? `?${qs}` : ""}`;
  return apiFetch(url, {}, "Memory metrics fetch failed");
}

// Fetch top performing memories
export async function fetchTopMemories(params?: {
  sortBy?: string;
  limit?: number;
  groupId?: string;
}): Promise<TopMemory[]> {
  const searchParams = new URLSearchParams();
  if (params?.sortBy) searchParams.set("sort_by", params.sortBy);
  if (params?.limit) searchParams.set("limit", params.limit.toString());
  if (params?.groupId) searchParams.set("group_id", params.groupId);

  const qs = searchParams.toString();
  const url = `${API_BASE}/memory/analytics/top-memories${qs ? `?${qs}` : ""}`;
  return apiFetch(url, {}, "Top memories fetch failed");
}

// Fetch tier change history
export async function fetchTierChanges(params?: {
  days?: number;
}): Promise<TierChangesSummary> {
  const searchParams = new URLSearchParams();
  if (params?.days) searchParams.set("days", params.days.toString());

  const qs = searchParams.toString();
  const url = `${API_BASE}/memory/analytics/tier-changes${qs ? `?${qs}` : ""}`;
  return apiFetch(url, {}, "Tier changes fetch failed");
}

// Generate session summary
export async function generateSessionSummary(
  sessionId: string,
): Promise<SessionSummary> {
  return apiFetch(
    `${API_BASE}/memory/sessions/${sessionId}/summarize`,
    { method: "POST" },
    "Session summary generation failed",
  );
}

// Fetch continuity context (cross-session context)
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
