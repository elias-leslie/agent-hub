import { fetchApi } from "@/lib/api-config";

export type ModelPricingUnit =
  | "per_million_tokens"
  | "per_image"
  | "per_second"
  | "per_minute"
  | "per_million_characters";

export interface ModelCost {
  input_per_m: number;
  output_per_m: number;
  pricing_unit: ModelPricingUnit;
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

export interface CatalogDiscoveryProvider {
  provider_id: string;
  provider_name: string;
  unmatched_count: number;
  sample_model_ids: string[];
}

export interface CatalogDiscovery {
  unmatched_model_count: number;
  unmatched_provider_count: number;
  top_providers: CatalogDiscoveryProvider[];
  sample_model_ids: string[];
}

export interface CatalogHealth {
  total_models: number;
  enriched_models: number;
  unenriched_models: number;
  models_with_live_pricing: number;
  models_missing_live_pricing: number;
  is_stale: boolean;
  stale_after_hours: number;
  sync_status: string | null;
  sync_error: string | null;
  source_counts: Record<string, number> | null;
  discovery: CatalogDiscovery | null;
}

export interface CatalogModel {
  id: string;
  name: string;
  alias: string;
  hint: string;
  provider: string;
  cost: ModelCost;
  context_window: number;
  speed_tier: string;
  capabilities: ModelCapabilities;
  release_date?: string | null;
  knowledge_cutoff?: string | null;
  family?: string | null;
  enrichment?: ModelEnrichment | null;
  scores: {
    coding: number;
    reasoning: number;
    planning: number;
    tool_use: number;
    instruction: number;
    design: number;
    composite: number;
  };
}

export interface ModelsResponse {
  models: CatalogModel[];
  providers: Record<string, string>;
  last_sync: string | null;
  last_model_review: string | null;
  catalog_health: CatalogHealth | null;
}

let cachedResponse: ModelsResponse | null = null;
let fetchPromise: Promise<ModelsResponse> | null = null;

async function fetchModelsResponse(): Promise<ModelsResponse> {
  const res = await fetchApi("/api/models");
  if (!res.ok) {
    throw new Error(`Failed to fetch models: ${res.status}`);
  }
  return res.json();
}

export async function getModelsResponse(): Promise<ModelsResponse> {
  if (cachedResponse) return cachedResponse;
  if (!fetchPromise) {
    fetchPromise = fetchModelsResponse().then((response) => {
      cachedResponse = response;
      fetchPromise = null;
      return response;
    }).catch((error) => {
      fetchPromise = null;
      throw error;
    });
  }
  return fetchPromise;
}

export async function getModels(): Promise<CatalogModel[]> {
  return (await getModelsResponse()).models;
}

export function getCachedModels(): CatalogModel[] {
  return cachedResponse?.models ?? [];
}
