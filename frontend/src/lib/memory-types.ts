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
  updated_at?: string | null;
  valid_at: string;
  // ACE-aligned usage stats
  loaded_count?: number;
  referenced_count?: number;
  helpful_count?: number;
  harmful_count?: number;
  utility_score?: number;
  // Lifecycle scoring
  lifecycle_score?: number;
  // Context-aware injection
  trigger_task_types?: string[];
  pinned?: boolean;
  tags?: string[];
  // TOON reference index
  summary?: string;
}

// Sort options for memory list
export type MemorySortBy = "updated_at" | "created_at" | "utility_score" | "loaded_count";
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

export interface TopMemory {
  uuid: string;
  content: string;
  injection_tier: string;
  utility_score: number;
  loaded_count: number;
  referenced_count: number;
  lifecycle_score: number | null;
}

export interface TierChangeEntry {
  episode_uuid: string;
  old_tier: string;
  new_tier: string;
  change_type: string;
  lifecycle_score_before: number | null;
  lifecycle_score_after: number | null;
  created_at: string | null;
}

export interface TierChangesSummary {
  by_type: Record<string, { count: number; latest: string | null }>;
  recent: TierChangeEntry[];
  total: number;
}

export interface VariantMetrics {
  variant: string;
  injection_count: number;
  success_count: number;
  fail_count: number;
  unknown_count: number;
  success_rate: number;
  citation_rate: number;
  avg_latency_ms: number;
  avg_tokens: number;
}

export interface TimePeriodMetrics {
  period: string;
  injection_count: number;
  avg_success_rate: number;
  avg_citation_rate: number;
}

export interface MetricsDashboard {
  total_injections: number;
  period_start: string;
  period_end: string;
  period_granularity: string;
  by_variant: VariantMetrics[];
  by_period: TimePeriodMetrics[];
  overall_success_rate: number;
  overall_citation_rate: number;
  outcomes: OutcomeSummary;
}

export interface UsageTotals {
  loaded: number;
  cited: number;
  helpful: number;
  harmful: number;
  success?: number;
}

export interface OutcomeSummary {
  success_count: number;
  fail_count: number;
  unknown_count: number;
  known_count: number;
  coverage_rate: number;
  success_rate: number;
}

export interface MemoryAnalyticsState {
  total_episodes: number;
  tier_distribution: TierDistribution[];
  scope_distribution: ScopeDistribution[];
  usage_totals: UsageTotals;
  avg_utility_score: number;
  avg_lifecycle_score: number;
  lifecycle_by_tier: Record<string, number>;
  top_memories: TopMemory[];
}

export interface MemoryUtilizationMetrics {
  injection_sessions: number;
  citation_sessions: number;
  lookup_sessions: number;
  lookup_after_injection_sessions: number;
  memory_search_calls: number;
  memory_get_calls: number;
  assistant_message_count: number;
  assistant_messages_with_memory_citations: number;
  citation_session_rate: number;
  lookup_session_rate: number;
  expansion_session_rate: number;
  assistant_citation_rate: number;
  sessions_with_selected_references: number;
  sessions_with_cited_selected_references: number;
  selected_reference_count: number;
  selected_reference_cited_count: number;
  selected_reference_citation_rate: number;
  selected_reference_session_rate: number;
  memory_inject_event_count: number;
  memory_inject_events_with_debug: number;
  memory_debug_coverage_rate: number;
}

export interface MemoryAnalyticsActivity {
  lookback: string;
  usage_totals: UsageTotals & { success: number };
  injection_metrics: MetricsDashboard;
  utilization: MemoryUtilizationMetrics;
  tier_changes: TierChangesSummary;
}

export interface MemoryAnalyticsDashboard {
  state: MemoryAnalyticsState;
  activity: MemoryAnalyticsActivity;
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
