/**
 * Memory API client for Agent Hub.
 * Barrel export for all memory-related operations.
 */

// Re-export all types
export * from "./memory-types";

// Re-export utility functions
export { exportMemoriesAsJson, downloadJson } from "./memory-utils";

// Re-export episode operations
export {
  fetchMemoryList,
  fetchMemoryGroups,
  deleteMemory,
  bulkDeleteMemories,
  addEpisode,
  updateEpisodeTier,
  updateEpisodeProperties,
  batchUpdateTier,
  fetchEpisodeCitations,
  fetchSimilarEpisodes,
  rateEpisode,
} from "./memory/episodes";

// Re-export search & analytics operations
export {
  fetchMemoryStats,
  searchMemories,
  fetchTimeline,
  fetchMemoryAnalytics,
  fetchMemoryMetrics,
  fetchTopMemories,
  fetchTierChanges,
  generateSessionSummary,
  fetchContinuityContext,
} from "./memory/search";
