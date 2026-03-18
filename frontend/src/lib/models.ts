/**
 * Single source of truth for model information on the frontend.
 * Fetches from /api/models (backend catalog) and caches in memory.
 */

import { fetchApi } from "@/lib/api-config";

export interface ModelCost {
  input_per_m: number;
  output_per_m: number;
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
}

export interface ModelsResponse {
  models: CatalogModel[];
  last_sync: string | null;
  last_model_review: string | null;
}

// Static fallback for SSR/offline — just names, no costs
const FALLBACK_CLAUDE_SONNET_4_6: CatalogModel = {
  id: "claude-sonnet-4-6",
  name: "Claude Sonnet 4.6",
  alias: "sonnet",
  hint: "Balanced",
  provider: "claude",
  cost: { input_per_m: 3, output_per_m: 15 },
  context_window: 1_000_000,
  speed_tier: "medium",
  capabilities: {
    can_generate_images: false,
    has_vision: true,
    can_edit_images: false,
    has_thinking: true,
    supports_pdf: true,
    supports_audio: false,
    supports_tool_execution: true,
    supports_verbosity: false,
    supports_xhigh: false,
    supports_session_cache: false,
    max_output_tokens: 16384,
  },
};

const FALLBACK_CLAUDE_OPUS_4_6: CatalogModel = {
  id: "claude-opus-4-6",
  name: "Claude Opus 4.6",
  alias: "opus",
  hint: "Powerful",
  provider: "claude",
  cost: { input_per_m: 5, output_per_m: 25 },
  context_window: 1_000_000,
  speed_tier: "slow",
  capabilities: {
    can_generate_images: false,
    has_vision: true,
    can_edit_images: false,
    has_thinking: true,
    supports_pdf: true,
    supports_audio: false,
    supports_tool_execution: true,
    supports_verbosity: false,
    supports_xhigh: false,
    supports_session_cache: false,
    max_output_tokens: 32768,
  },
};

const FALLBACK_CLAUDE_HAIKU_4_5: CatalogModel = {
  id: "claude-haiku-4-5",
  name: "Claude Haiku 4.5",
  alias: "haiku",
  hint: "Quick",
  provider: "claude",
  cost: { input_per_m: 1, output_per_m: 5 },
  context_window: 200_000,
  speed_tier: "fast",
  capabilities: {
    can_generate_images: false,
    has_vision: true,
    can_edit_images: false,
    has_thinking: false,
    supports_pdf: true,
    supports_audio: false,
    supports_tool_execution: true,
    supports_verbosity: false,
    supports_xhigh: false,
    supports_session_cache: false,
    max_output_tokens: 8192,
  },
};

const FALLBACK_GEMINI_3_FLASH: CatalogModel = {
  id: "gemini-3-flash-preview",
  name: "Gemini 3 Flash",
  alias: "flash",
  hint: "Fast",
  provider: "gemini",
  cost: { input_per_m: 0.5, output_per_m: 3 },
  context_window: 1_000_000,
  speed_tier: "fast",
  capabilities: {
    can_generate_images: true,
    has_vision: true,
    can_edit_images: true,
    has_thinking: true,
    supports_pdf: true,
    supports_audio: true,
    supports_tool_execution: true,
    supports_verbosity: false,
    supports_xhigh: false,
    supports_session_cache: false,
    max_output_tokens: 65536,
  },
};

const FALLBACK_GEMINI_3_1_FLASH_LITE: CatalogModel = {
  id: "gemini-3.1-flash-lite-preview",
  name: "Gemini 3.1 Flash Lite",
  alias: "3.1-flash-lite",
  hint: "High Throughput",
  provider: "gemini",
  cost: { input_per_m: 0.1, output_per_m: 0.4 },
  context_window: 1_000_000,
  speed_tier: "fast",
  capabilities: {
    can_generate_images: false,
    has_vision: true,
    can_edit_images: false,
    has_thinking: false,
    supports_pdf: true,
    supports_audio: false,
    supports_tool_execution: false,
    supports_verbosity: false,
    supports_xhigh: false,
    supports_session_cache: false,
    max_output_tokens: 8192,
  },
};

const FALLBACK_GEMINI_3_1_PRO: CatalogModel = {
  id: "gemini-3.1-pro-preview",
  name: "Gemini 3.1 Pro",
  alias: "3.1-pro",
  hint: "Deep Reasoning",
  provider: "gemini",
  cost: { input_per_m: 3, output_per_m: 15 },
  context_window: 1_000_000,
  speed_tier: "slow",
  capabilities: {
    can_generate_images: false,
    has_vision: true,
    can_edit_images: false,
    has_thinking: true,
    supports_pdf: true,
    supports_audio: false,
    supports_tool_execution: true,
    supports_verbosity: false,
    supports_xhigh: false,
    supports_session_cache: false,
    max_output_tokens: 65536,
  },
};

const FALLBACK_GPT_5_4_CODEX: CatalogModel = {
  id: "codex/gpt-5.4",
  name: "GPT-5.4 (Codex)",
  alias: "codex-5.4",
  hint: "Frontier",
  provider: "codex",
  cost: { input_per_m: 2.5, output_per_m: 15 },
  context_window: 1_050_000,
  speed_tier: "medium",
  capabilities: {
    can_generate_images: false,
    has_vision: true,
    can_edit_images: false,
    has_thinking: true,
    supports_pdf: true,
    supports_audio: false,
    supports_tool_execution: true,
    supports_verbosity: true,
    supports_xhigh: true,
    supports_session_cache: true,
    max_output_tokens: 32768,
  },
};

const FALLBACK_GPT_5_3_CODEX: CatalogModel = {
  id: "codex/gpt-5.3-codex",
  name: "GPT-5.3 Codex",
  alias: "codex",
  hint: "Best Coding",
  provider: "codex",
  cost: { input_per_m: 1.75, output_per_m: 14 },
  context_window: 400_000,
  speed_tier: "fast",
  capabilities: {
    can_generate_images: false,
    has_vision: true,
    can_edit_images: false,
    has_thinking: true,
    supports_pdf: false,
    supports_audio: false,
    supports_tool_execution: true,
    supports_verbosity: true,
    supports_xhigh: false,
    supports_session_cache: true,
    max_output_tokens: 32768,
  },
};

const FALLBACK_GPT_5_3_CODEX_SPARK: CatalogModel = {
  id: "codex/gpt-5.3-codex-spark",
  name: "GPT-5.3 Codex Spark",
  alias: "codex-spark",
  hint: "Real-Time Coding",
  provider: "codex",
  cost: { input_per_m: 1, output_per_m: 8 },
  context_window: 400_000,
  speed_tier: "fast",
  capabilities: {
    can_generate_images: false,
    has_vision: true,
    can_edit_images: false,
    has_thinking: true,
    supports_pdf: false,
    supports_audio: false,
    supports_tool_execution: true,
    supports_verbosity: true,
    supports_xhigh: false,
    supports_session_cache: true,
    max_output_tokens: 16384,
  },
};

const FALLBACK_GPT_5_2_CODEX: CatalogModel = {
  id: "codex/gpt-5.2-codex",
  name: "GPT-5.2 Codex",
  alias: "codex-5.2",
  hint: "Coding Stable",
  provider: "codex",
  cost: { input_per_m: 2, output_per_m: 12 },
  context_window: 400_000,
  speed_tier: "medium",
  capabilities: {
    can_generate_images: false,
    has_vision: true,
    can_edit_images: false,
    has_thinking: true,
    supports_pdf: false,
    supports_audio: false,
    supports_tool_execution: true,
    supports_verbosity: true,
    supports_xhigh: false,
    supports_session_cache: true,
    max_output_tokens: 32768,
  },
};

const STATIC_FALLBACK: CatalogModel[] = [
  FALLBACK_CLAUDE_SONNET_4_6,
  FALLBACK_CLAUDE_OPUS_4_6,
  FALLBACK_CLAUDE_HAIKU_4_5,
  FALLBACK_GEMINI_3_FLASH,
  FALLBACK_GEMINI_3_1_FLASH_LITE,
  FALLBACK_GEMINI_3_1_PRO,
  FALLBACK_GPT_5_4_CODEX,
  FALLBACK_GPT_5_3_CODEX,
  FALLBACK_GPT_5_3_CODEX_SPARK,
  FALLBACK_GPT_5_2_CODEX,
];

let cachedModels: CatalogModel[] | null = null;
let cachedLastSync: string | null = null;
let fetchPromise: Promise<CatalogModel[]> | null = null;

async function fetchModelsFromApi(): Promise<CatalogModel[]> {
  try {
    const res = await fetchApi("/api/models");
    if (!res.ok) throw new Error(`Failed to fetch models: ${res.status}`);
    const data: ModelsResponse = await res.json();
    cachedLastSync = data.last_sync;
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

