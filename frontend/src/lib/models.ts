/**
 * Single source of truth for model information on the frontend.
 * Fetches from /api/models (backend catalog) and caches in memory.
 */

import { fetchApi } from "@/lib/api-config";

export interface ModelCost {
  input_per_m: number;
  output_per_m: number;
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
  capabilities: {
    can_generate_images: boolean;
    has_vision: boolean;
    can_edit_images: boolean;
  };
}

// Static fallback for SSR/offline — just names, no costs
const STATIC_FALLBACK: CatalogModel[] = [
  { id: "claude-sonnet-4-6", name: "Claude Sonnet 4.6", alias: "sonnet", hint: "Balanced", provider: "claude", cost: { input_per_m: 3, output_per_m: 15 }, context_window: 1_000_000, speed_tier: "medium", capabilities: { can_generate_images: false, has_vision: true, can_edit_images: false } },
  { id: "claude-opus-4-6", name: "Claude Opus 4.6", alias: "opus", hint: "Powerful", provider: "claude", cost: { input_per_m: 5, output_per_m: 25 }, context_window: 1_000_000, speed_tier: "slow", capabilities: { can_generate_images: false, has_vision: true, can_edit_images: false } },
  { id: "claude-haiku-4-5", name: "Claude Haiku 4.5", alias: "haiku", hint: "Quick", provider: "claude", cost: { input_per_m: 1, output_per_m: 5 }, context_window: 200_000, speed_tier: "fast", capabilities: { can_generate_images: false, has_vision: true, can_edit_images: false } },
  { id: "gemini-3-flash-preview", name: "Gemini 3 Flash", alias: "flash", hint: "Fast", provider: "gemini", cost: { input_per_m: 0.5, output_per_m: 3 }, context_window: 1_000_000, speed_tier: "fast", capabilities: { can_generate_images: true, has_vision: true, can_edit_images: true } },
  { id: "gemini-3-pro-preview", name: "Gemini 3 Pro", alias: "pro", hint: "Reasoning", provider: "gemini", cost: { input_per_m: 3, output_per_m: 15 }, context_window: 1_000_000, speed_tier: "medium", capabilities: { can_generate_images: true, has_vision: true, can_edit_images: true } },
];

let cachedModels: CatalogModel[] | null = null;
let fetchPromise: Promise<CatalogModel[]> | null = null;

async function fetchModelsFromApi(): Promise<CatalogModel[]> {
  try {
    const res = await fetchApi("/api/models");
    if (!res.ok) throw new Error(`Failed to fetch models: ${res.status}`);
    const data = await res.json();
    return data.models || STATIC_FALLBACK;
  } catch {
    return STATIC_FALLBACK;
  }
}

/** Get all models from catalog (fetches once, caches in memory). */
export async function getModels(): Promise<CatalogModel[]> {
  if (cachedModels) return cachedModels;
  if (!fetchPromise) {
    fetchPromise = fetchModelsFromApi().then((models) => {
      cachedModels = models;
      fetchPromise = null;
      return models;
    });
  }
  return fetchPromise;
}

/** Invalidate the cached models (e.g., after config changes). */
export function invalidateModelCache(): void {
  cachedModels = null;
  fetchPromise = null;
}

// Build a name lookup from cached models + legacy display-only map
const LEGACY_NAMES: Record<string, string> = {
  "claude-sonnet-4-5": "Claude Sonnet 4.5",
  "claude-sonnet-4-5-20250514": "Claude Sonnet 4.5",
  "claude-opus-4-5": "Claude Opus 4.5",
  "claude-opus-4-5-20250514": "Claude Opus 4.5",
  "claude-haiku-4-5-20250514": "Claude Haiku 4.5",
};

/** Format a model ID to a human-readable display name. */
export function formatModelName(modelId?: string): string {
  if (!modelId) return "Assistant";

  // Check cached catalog first
  if (cachedModels) {
    const entry = cachedModels.find((m) => m.id === modelId);
    if (entry) return entry.name;
  }

  // Static fallback lookup
  const fallback = STATIC_FALLBACK.find((m) => m.id === modelId);
  if (fallback) return fallback.name;

  // Legacy display-only (old session data)
  if (modelId in LEGACY_NAMES) return LEGACY_NAMES[modelId];

  return modelId;
}

/** Get cost per 1M tokens for a model. */
export function getModelCost(modelId: string): ModelCost {
  if (cachedModels) {
    const entry = cachedModels.find((m) => m.id === modelId);
    if (entry) return entry.cost;
  }
  const fallback = STATIC_FALLBACK.find((m) => m.id === modelId);
  if (fallback) return fallback.cost;
  return { input_per_m: 2, output_per_m: 8 }; // reasonable default
}

/** Model alias map: alias → model ID, derived from catalog. */
export function getModelAliases(): Record<string, { model: string; label: string }> {
  const source = cachedModels || STATIC_FALLBACK;
  const aliases: Record<string, { model: string; label: string }> = {};
  for (const m of source) {
    aliases[m.alias] = { model: m.id, label: m.name.split(" ").pop() || m.alias };
  }
  return aliases;
}
