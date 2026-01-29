// ─────────────────────────────────────────────────────────────────────────────
// API
// ─────────────────────────────────────────────────────────────────────────────

import { fetchApi } from "@/lib/api-config";
import type { AgentListResponse, AgentMetricsResponse } from "./types";

export async function fetchAgents(activeOnly = true): Promise<AgentListResponse> {
  const params = new URLSearchParams();
  params.set("active_only", String(activeOnly));

  const res = await fetchApi(`/api/agents?${params}`);
  if (!res.ok) {
    throw new Error("Failed to fetch agents");
  }
  return res.json();
}

export async function fetchMetrics(): Promise<AgentMetricsResponse> {
  const res = await fetchApi("/api/agents/metrics/all");
  if (!res.ok) {
    // Return empty metrics on error - don't fail the whole page
    return { metrics: {} };
  }
  return res.json();
}
