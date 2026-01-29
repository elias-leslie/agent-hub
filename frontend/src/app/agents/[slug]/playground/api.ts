// ─────────────────────────────────────────────────────────────────────────────
// API
// ─────────────────────────────────────────────────────────────────────────────

import { fetchApi } from "@/lib/api-config";
import type { Agent, AgentPreview } from "./types";

export async function fetchAgent(slug: string): Promise<Agent> {
  const res = await fetchApi(`/api/agents/${slug}`);
  if (!res.ok) throw new Error("Failed to fetch agent");
  return res.json();
}

export async function fetchAgents(): Promise<{ agents: Agent[] }> {
  const res = await fetchApi("/api/agents?active_only=true");
  if (!res.ok) throw new Error("Failed to fetch agents");
  return res.json();
}

export async function fetchPreview(slug: string): Promise<AgentPreview> {
  const res = await fetchApi(`/api/agents/${slug}/preview`);
  if (!res.ok) throw new Error("Failed to fetch preview");
  return res.json();
}
