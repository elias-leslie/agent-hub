import { fetchApi } from "@/lib/api-config";
import { Agent, AgentPreview, ModelInfo } from "@/app/agents/[slug]/types";

export async function fetchAgent(slug: string): Promise<Agent> {
  const res = await fetchApi(`/api/agents/${slug}`);
  if (!res.ok) throw new Error("Failed to fetch agent");
  return res.json();
}

export async function updateAgent(
  slug: string,
  data: Partial<Agent>
): Promise<Agent> {
  const res = await fetchApi(`/api/agents/${slug}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update agent");
  return res.json();
}

export async function fetchPreview(slug: string): Promise<AgentPreview> {
  const res = await fetchApi(`/api/agents/${slug}/preview`);
  if (!res.ok) throw new Error("Failed to fetch preview");
  return res.json();
}

export async function fetchModels(): Promise<ModelInfo[]> {
  const { getModels } = await import("@/lib/models");
  try {
    const models = await getModels();
    return models.map((m) => ({ id: m.id, name: m.name, provider: m.provider }));
  } catch {
    return [];
  }
}
