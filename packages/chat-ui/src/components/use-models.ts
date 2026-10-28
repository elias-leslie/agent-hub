import { useQuery } from "@tanstack/react-query";
import { useChatClient, type ChatHubClient } from "../client";

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
  routable: boolean;
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

/**
 * The model catalog through the client's `models.list()`. Empty until it loads, and when there is no client or
 * `enabled` is false (nothing is fetched then).
 */
export function useModels(client?: ChatHubClient | null, options: { enabled?: boolean } = {}): ModelOption[] {
  const resolved = useChatClient(client);
  const { data } = useQuery({
    queryKey: ["agent-hub-chat-ui", "models", resolved?.baseUrl ?? ""],
    queryFn: async () => (await resolved!.models.list()) as unknown as ModelOption[],
    enabled: Boolean(resolved) && (options.enabled ?? true),
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return data ?? [];
}
