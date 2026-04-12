/**
 * API client for Agent Hub backend.
 * Uses getApiBaseUrl() from api-config.ts for proper URL resolution.
 *
 * This file serves as the main export point for all API functions.
 * Individual modules are organized by resource type in the ./api/ directory.
 */

// Re-export all status-related exports
export type {
  CircuitBreakerStatus,
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
  OAuthAuthorizeResponse,
  OAuthStatusResponse,
  OAuthExchangeResponse,
  SetPrimaryCredentialResponse,
} from "./api/credentials";
export {
  fetchCredentials,
  createCredential,
  updateCredential,
  deleteCredential,
  setPrimaryCredential,
  fetchClaudeOAuthStatus,
  startOAuthFlow,
  fetchOAuthStatus,
  exchangeOAuthCode,
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
  fetchAllSessionEvents,
} from "./api/sessions";

// Re-export all preferences-related exports
export type { UserPreferences } from "./api/preferences";
export {
  fetchUserPreferences,
  updateUserPreferences,
} from "./api/preferences";

// Re-export all agents-related exports (list & metrics)
export { fetchAgents, fetchAgentBenchmarkDashboard, fetchAgentBenchmarkRunDetail, fetchAgentMetrics } from "./api/agents";
export { fetchArenaOverview } from "./api/arena";
export {
  fetchPersonaImprovementDashboard,
  updatePersonaImprovementSchedule,
} from "./api/persona-improvement";
export { fetchPersona, PERSONA_QUERY_KEY } from "./api/persona";

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
export type {
  BlockedRequest,
  ClientControl,
  HotspotBreakdownRow,
  HotspotTotals,
  LowYieldSessionRow,
  RepeatedWorkloadRow,
  SessionHotspots,
  WorkflowSchedule,
  WorkflowScheduleUpdate,
  ZeroEventActiveSessionRow,
} from "./api/admin";
export {
  fetchClients,
  fetchBlockedRequests,
  fetchSessionHotspots,
  fetchWorkflowSchedules,
  disableClient,
  enableClient,
  updateWorkflowSchedule,
} from "./api/admin";

// Re-export all project-permissions-related exports
export type {
  ProjectPermission,
  ProjectPermissionCreate,
  ProjectPermissionUpdate,
  ExecutionPermission,
} from "./api/project-permissions";
export {
  createProjectPermission,
  fetchProjectPermissions,
  updateProjectPermission,
  fetchExecutionPermission,
} from "./api/project-permissions";

// Re-export all budget-related exports
export type {
  BudgetUsage,
  ProjectBudget,
  BudgetSettingsUpdate,
} from "./api/budgets";
export {
  fetchAllProjectBudgets,
  updateBudgetSettings,
} from "./api/budgets";
