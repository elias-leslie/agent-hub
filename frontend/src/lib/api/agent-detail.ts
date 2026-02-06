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
  try {
    const res = await fetchApi("/api/models");
    if (!res.ok) throw new Error("Failed to fetch models");
    const data = await res.json();
    return data.models || [];
  } catch {
    return [
      { id: "claude-sonnet-4-5", name: "Claude Sonnet 4.5", provider: "claude" },
      { id: "claude-haiku-4-5", name: "Claude Haiku 4.5", provider: "claude" },
      { id: "gemini-3-flash-preview", name: "Gemini 3 Flash", provider: "gemini" },
      { id: "openrouter/x-ai/grok-code-fast-1", name: "Grok Code Fast 1 (OR)", provider: "openrouter" },
      { id: "openrouter/moonshotai/kimi-k2.5", name: "Kimi K2.5 (OR)", provider: "openrouter" },
    ];
  }
}
