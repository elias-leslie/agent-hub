/**
 * API client for Agent Hub backend.
 * Uses getApiBaseUrl() from api-config.ts for proper URL resolution.
 *
 * This file serves as the main export point for all API functions.
 * Individual modules are organized by resource type in the ./api/ directory.
 */

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
} from './api/admin'
export {
  disableClient,
  enableClient,
  fetchBlockedRequests,
  fetchClients,
  fetchSessionHotspots,
  fetchWorkflowSchedules,
  updateWorkflowSchedule,
} from './api/admin'
// Re-export all agent-detail-related exports
export {
  fetchAgent,
  fetchAgentRouting,
  fetchModels,
  fetchPreview,
  updateAgent,
  updateAgentRouting,
  updateAgentWorkloadRouting,
} from './api/agent-detail'
// Re-export all agents-related exports (list & metrics)
export {
  fetchAgentBenchmarkDashboard,
  fetchAgentBenchmarkRunDetail,
  fetchAgentMetrics,
  fetchAgents,
} from './api/agents'
// Re-export all analytics-related exports
export type {
  CostAggregation,
  CostAggregationResponse,
  TruncationAggregation,
  TruncationMetricsResponse,
} from './api/analytics'
export { fetchCosts, fetchTruncations } from './api/analytics'
export { fetchArenaOverview } from './api/arena'
// Re-export all budget-related exports
export type {
  BudgetSettingsUpdate,
  BudgetUsage,
  ProjectBudget,
} from './api/budgets'
export {
  fetchAllProjectBudgets,
  updateBudgetSettings,
} from './api/budgets'
// Re-export all credentials-related exports
export type {
  ClaudeOAuthStatus,
  Credential,
  CredentialCreate,
  CredentialListResponse,
  OAuthAuthorizeResponse,
  OAuthExchangeResponse,
  OAuthStatusResponse,
  SetPrimaryCredentialResponse,
} from './api/credentials'
export {
  createCredential,
  deleteCredential,
  exchangeOAuthCode,
  fetchClaudeOAuthStatus,
  fetchCredentials,
  fetchOAuthStatus,
  setPrimaryCredential,
  startOAuthFlow,
  updateCredential,
} from './api/credentials'
// Re-export all dashboard-related exports
export type {
  DashboardStatsResponse,
  MemoryMetrics,
  ModelBreakdown,
  RequestMetrics,
  TruncationMetrics,
} from './api/dashboard'
export { fetchDashboardStats } from './api/dashboard'
// Re-export all monitoring-related exports
export { fetchMonitoringMetrics, fetchRequestLog } from './api/monitoring'
export { fetchPersona, PERSONA_QUERY_KEY } from './api/persona'
export {
  fetchPersonaImprovementDashboard,
  updatePersonaImprovementSchedule,
} from './api/persona-improvement'
// Re-export all preferences-related exports
export type { UserPreferences } from './api/preferences'
export {
  fetchUserPreferences,
  updateUserPreferences,
} from './api/preferences'
// Re-export all project-permissions-related exports
export type {
  ExecutionPermission,
  ProjectPermission,
  ProjectPermissionCreate,
  ProjectPermissionUpdate,
  ProjectRoots,
} from './api/project-permissions'
export {
  createProjectPermission,
  fetchExecutionPermission,
  fetchProjectPermissions,
  fetchProjectRoots,
  updateProjectPermission,
} from './api/project-permissions'
// Re-export all sessions-related exports
export type {
  AgentTokenBreakdown,
  ContextUsage,
  Session,
  SessionEventsResponse,
  SessionListItem,
  SessionListResponse,
  SessionMessage,
  SessionTimelineEvent,
} from './api/sessions'
export {
  fetchAllSessionEvents,
  fetchSession,
  fetchSessionEvents,
  fetchSessions,
} from './api/sessions'
// Re-export all status-related exports
export type {
  CircuitBreakerStatus,
  ProviderHealthDetails,
  ProviderStatus,
  StatusResponse,
} from './api/status'
export { fetchStatus } from './api/status'
