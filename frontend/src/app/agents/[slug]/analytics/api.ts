import { fetchApi } from "@/lib/api-config";
import type { Agent, AgentMetrics } from "./types";

export async function fetchAgent(slug: string): Promise<Agent> {
  const res = await fetchApi(`/api/agents/${slug}`);
  if (!res.ok) throw new Error("Failed to fetch agent");
  return res.json();
}

export async function fetchAgentMetrics(slug: string): Promise<AgentMetrics> {
  const res = await fetchApi(`/api/agents/${slug}/metrics`);
  if (!res.ok) throw new Error("Failed to fetch metrics");
  return res.json();
}
