// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

export interface RequestLogEntry {
  id: number;
  client_id: string | null;
  client_display_name: string | null;
  request_source: string | null;
  endpoint: string;
  method: string;
  status_code: number;
  rejection_reason: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  latency_ms: number | null;
  model: string | null;
  agent_slug: string | null;
  tool_type: string | null;
  tool_name: string | null;
  source_path: string | null;
  created_at: string;
}

export interface RequestLogResponse {
  requests: RequestLogEntry[];
  total: number;
}

export interface MetricsSummary {
  total_requests: number;
  success_rate: number;
  avg_latency_ms: number;
}

export interface ToolTypeBreakdown {
  tool_type: string;
  count: number;
}

export interface EndpointMetric {
  endpoint: string;
  count: number;
  success_rate: number;
  avg_latency_ms: number;
}

export interface ToolNameMetric {
  tool_name: string;
  count: number;
  avg_latency_ms: number;
  success_rate: number;
}

export interface MetricsResponse {
  summary: MetricsSummary;
  by_tool_type: ToolTypeBreakdown[];
  by_tool_name: ToolNameMetric[];
  by_endpoint: EndpointMetric[];
}

export type SortField = "time" | "type" | "tool" | "agent" | "status" | "latency";
export type SortDirection = "asc" | "desc";
