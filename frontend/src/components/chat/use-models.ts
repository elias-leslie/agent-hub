import { useQuery } from "@tanstack/react-query";
import { fetchApi } from "@/lib/api-config";

export interface ModelScores {
  coding: number;
  reasoning: number;
  planning: number;
  tool_use: number;
  instruction: number;
  design: number;
  composite: number;
}

export interface ModelCost {
  input_per_m: number;
  output_per_m: number;
}

export interface ModelCapabilities {
  can_generate_images: boolean;
  has_vision: boolean;
  can_edit_images: boolean;
}

export interface ModelOption {
  id: string;
  alias: string;
  name: string;
  hint: string;
  provider: "claude" | "gemini" | "openrouter" | "openai" | "xai" | "zhipu" | "minimax";
  scores: ModelScores;
  cost: ModelCost;
  context_window: number;
  speed_tier: "fast" | "medium" | "slow";
  capabilities: ModelCapabilities;
}

async function fetchModels(): Promise<ModelOption[]> {
  const response = await fetchApi("/api/models");
  if (!response.ok) {
    throw new Error(`Failed to fetch models: ${response.status}`);
  }
  const data = await response.json();
  return data.models;
}

export function useModels(): ModelOption[] {
  const { data } = useQuery({
    queryKey: ["models"],
    queryFn: fetchModels,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return data ?? [];
}
