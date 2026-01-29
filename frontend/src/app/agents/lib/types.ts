// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

export interface Agent {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  primary_model_id: string;
  fallback_models: string[];
  temperature: number;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface AgentListResponse {
  agents: Agent[];
  total: number;
}

export interface AgentMetrics {
  slug: string;
  requests_24h: number;
  avg_latency_ms: number;
  success_rate: number;
  tokens_24h: number;
  cost_24h_usd: number;
  latency_trend: number[];
  success_trend: number[];
}

export interface AgentMetricsResponse {
  metrics: Record<string, AgentMetrics>;
}

// Sort types
export type SortField = "name" | "model" | "status" | "requests" | "latency" | "success" | "version";
export type SortDirection = "asc" | "desc";
