import { useQuery } from "@tanstack/react-query";
import { fetchApi } from "@/lib/api-config";
import type {
  CatalogHealth,
  ModelCapabilities,
  ModelCost,
  ModelEnrichment,
} from "@/lib/models";

export type { ModelCapabilities, ModelCost, ModelEnrichment };

export interface ModelScores {
  coding: number;
  reasoning: number;
  planning: number;
  tool_use: number;
  instruction: number;
  design: number;
  composite: number;
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

export interface ModelsApiResponse {
  models: ModelOption[];
  providers: Record<string, string>;
  last_sync: string | null;
  last_model_review: string | null;
  catalog_health: CatalogHealth | null;
}

export const MODELS_CATALOG_QUERY_KEY = ["models", "catalog"] as const;

async function fetchModels(): Promise<ModelsApiResponse> {
  const response = await fetchApi("/api/models");
  if (!response.ok) {
    throw new Error(`Failed to fetch models: ${response.status}`);
  }
  return response.json();
}

export function useModels(): ModelOption[] {
  const { data } = useQuery({
    queryKey: MODELS_CATALOG_QUERY_KEY,
    queryFn: fetchModels,
    staleTime: Infinity,
    gcTime: Infinity,
    select: (d) => d.models,
  });
  return data ?? [];
}

export function useModelsWithSync() {
  const query = useQuery({
    queryKey: MODELS_CATALOG_QUERY_KEY,
    queryFn: fetchModels,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return {
    models: query.data?.models ?? [],
    providers: query.data?.providers ?? {},
    lastSync: query.data?.last_sync ?? null,
    lastModelReview: query.data?.last_model_review ?? null,
    catalogHealth: query.data?.catalog_health ?? null,
    refetch: query.refetch,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
  };
}
