/**
 * API client for Agent Hub backend.
 * Uses getApiBaseUrl() from api-config.ts for proper URL resolution.
 *
 * This file serves as the main export point for all API functions.
 * Individual modules are organized by resource type in the ./api/ directory.
 */

// Re-export all status-related exports
export type {
  ProviderHealthDetails,
  ProviderStatus,
  StatusResponse,
} from "./api/status";
export { fetchStatus } from "./api/status";

// Re-export all analytics-related exports
export type {
  CostAggregation,
  CostAggregationResponse,
  TruncationAggregation,
  TruncationMetricsResponse,
} from "./api/analytics";
export { fetchCosts, fetchTruncations } from "./api/analytics";

// Re-export all dashboard-related exports
export type {
  RequestMetrics,
  MemoryMetrics,
  TruncationMetrics,
  ModelBreakdown,
  DashboardStatsResponse,
} from "./api/dashboard";
export { fetchDashboardStats } from "./api/dashboard";

// Re-export all credentials-related exports
export type {
  Credential,
  CredentialListResponse,
  CredentialCreate,
  ClaudeOAuthStatus,
} from "./api/credentials";
export {
  fetchCredentials,
  createCredential,
  updateCredential,
  deleteCredential,
  fetchClaudeOAuthStatus,
} from "./api/credentials";

// Re-export all sessions-related exports
export type {
  SessionMessage,
  AgentTokenBreakdown,
  ContextUsage,
  Session,
  SessionListItem,
  SessionListResponse,
  SessionTimelineEvent,
  SessionEventsResponse,
} from "./api/sessions";
export {
  fetchSessions,
  fetchSession,
  fetchSessionEvents,
} from "./api/sessions";

// Re-export all preferences-related exports
export type { UserPreferences } from "./api/preferences";
export {
  fetchUserPreferences,
  updateUserPreferences,
} from "./api/preferences";

// Re-export all agents-related exports (list & metrics)
export { fetchAgents, fetchAgentMetrics } from "./api/agents";

// Re-export all agent-detail-related exports
export {
  fetchAgent,
  updateAgent,
  fetchPreview,
  fetchModels,
} from "./api/agent-detail";

// Re-export all monitoring-related exports
export { fetchRequestLog, fetchMonitoringMetrics } from "./api/monitoring";

// Re-export all admin-related exports
export type { ClientControl, BlockedRequest } from "./api/admin";
export {
  fetchClients,
  fetchBlockedRequests,
  disableClient,
  enableClient,
} from "./api/admin";
