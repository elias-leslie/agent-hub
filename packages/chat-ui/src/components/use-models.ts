import { useQuery } from "@tanstack/react-query";

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
  pricing_unit:
    | "per_million_tokens"
    | "per_image"
    | "per_second"
    | "per_minute"
    | "per_million_characters";
  unit_price: number | null;
  source: "catalog" | "enrichment";
}

export interface ModelCapabilities {
  can_generate_images: boolean;
  has_vision: boolean;
  can_edit_images: boolean;
  has_thinking: boolean;
  supports_pdf: boolean;
  supports_audio: boolean;
  supports_tool_execution: boolean;
  supports_verbosity: boolean;
  supports_xhigh: boolean;
  supports_session_cache: boolean;
  max_output_tokens: number;
}

export interface ModelEnrichment {
  ext_coding: number | null;
  ext_reasoning: number | null;
  ext_tool_use: number | null;
  ext_planning: number | null;
  ext_instruction: number | null;
  ext_speed_tier: string | null;
  ext_input_per_m: number | null;
  ext_output_per_m: number | null;
  source: string | null;
  synced_at: string | null;
}

export interface ModelOption {
  id: string;
  alias: string;
  name: string;
  hint: string;
  provider: string;
  scores: ModelScores;
  cost: ModelCost;
  context_window: number;
  speed_tier: "fast" | "medium" | "slow";
  capabilities: ModelCapabilities;
  release_date?: string | null;
  knowledge_cutoff?: string | null;
  family?: string | null;
  availability?: string | null;
  enrichment?: ModelEnrichment | null;
}

async function fetchModels(fetchFn: (url: string, options?: RequestInit) => Promise<Response>, endpoint: string): Promise<ModelOption[]> {
  const response = await fetchFn(endpoint);
  if (!response.ok) {
    throw new Error(`Failed to fetch models: ${response.status}`);
  }
  const data = await response.json();
  return data.models;
}

export function useModels(
  fetchFn: (url: string, options?: RequestInit) => Promise<Response> = fetch,
  modelsEndpoint: string = "/api/models",
): ModelOption[] {
  const { data } = useQuery({
    queryKey: ["models", modelsEndpoint],
    queryFn: () => fetchModels(fetchFn, modelsEndpoint),
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return data ?? [];
}
