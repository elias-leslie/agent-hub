import { buildApiUrl, fetchApi } from "@/lib/api-config";
import { RequestLogResponse, MetricsResponse } from "./types";

// ─────────────────────────────────────────────────────────────────────────────
// API FUNCTIONS
// ─────────────────────────────────────────────────────────────────────────────

export async function fetchRequestLog(params: {
  client_id?: string;
  status_code?: number;
  rejected_only?: boolean;
  tool_type?: string;
  agent_slug?: string;
  limit?: number;
  offset?: number;
}): Promise<RequestLogResponse> {
  const searchParams = new URLSearchParams();
  if (params.client_id) searchParams.set("client_id", params.client_id);
  if (params.status_code) searchParams.set("status_code", params.status_code.toString());
  if (params.rejected_only) searchParams.set("rejected_only", "true");
  if (params.tool_type) searchParams.set("tool_type", params.tool_type);
  if (params.agent_slug) searchParams.set("agent_slug", params.agent_slug);
  if (params.limit) searchParams.set("limit", params.limit.toString());
  if (params.offset) searchParams.set("offset", params.offset.toString());

  const response = await fetchApi(buildApiUrl(`/api/access-control/request-log?${searchParams.toString()}`));
  if (!response.ok) {
    throw new Error(`Failed to fetch request log: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchMetrics(hours: number = 24): Promise<MetricsResponse> {
  const response = await fetchApi(buildApiUrl(`/api/access-control/metrics?hours=${hours}&limit=10`));
  if (!response.ok) {
    throw new Error(`Failed to fetch metrics: ${response.statusText}`);
  }
  return response.json();
}
