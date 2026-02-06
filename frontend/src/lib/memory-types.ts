/**
 * Type definitions for Memory API.
 */

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
  pinned?: boolean;
  // TOON reference index
  summary?: string;
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

// Update episode tier response
export interface UpdateTierResponse {
  success: boolean;
  episode_id: string;
  injection_tier: string;
  message: string;
}

// Update episode properties request
export interface UpdateEpisodePropertiesRequest {
  pinned?: boolean;
  auto_inject?: boolean;
  display_order?: number;
  trigger_task_types?: string[];
  summary?: string;
}

// Update episode properties response
export interface UpdateEpisodePropertiesResponse {
  success: boolean;
  episode_id: string;
  pinned?: boolean;
  auto_inject?: boolean;
  display_order?: number;
  trigger_task_types?: string[];
  summary?: string;
  message: string;
}

// Timeline types
export interface TimelineGroup {
  label: string;
  date_key: string;
  episodes: MemoryEpisode[];
  count: number;
}

// Analytics types
export interface TierDistribution {
  tier: string;
  count: number;
  percentage: number;
}

export interface ScopeDistribution {
  scope: string;
  count: number;
  percentage: number;
}

export interface DailyTrend {
  date: string;
  count: number;
}

export interface MemoryAnalytics {
  total_episodes: number;
  tier_distribution: TierDistribution[];
  scope_distribution: ScopeDistribution[];
  total_loaded: number;
  total_cited: number;
  total_helpful: number;
  total_harmful: number;
  citation_rate: number;
  daily_trend: DailyTrend[];
  avg_utility_score: number;
}

export interface SessionSummary {
  session_id: string;
  summary: string;
  key_decisions: string[];
  tools_used: string[];
  files_modified: string[];
  topics: string[];
  generated_at: string;
  episode_uuid: string | null;
}

export interface ContinuityContext {
  markdown: string;
  session_count: number;
  days_covered: number;
}

export interface EpisodeCitation {
  session_id: string | null;
  project_id: string | null;
  created_at: string | null;
  variant: string;
}

export interface EpisodeCitationsResponse {
  episode_uuid: string;
  citations: EpisodeCitation[];
  total: number;
}

export interface SimilarEpisode {
  uuid: string;
  content: string;
  relevance_score: number;
  created_at: string | null;
}

export interface SimilarEpisodesResponse {
  episode_uuid: string;
  similar: SimilarEpisode[];
  total: number;
}
