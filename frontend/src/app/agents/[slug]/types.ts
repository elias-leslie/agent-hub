import type { CatalogModel } from "@/lib/models";
export type {
  AgentPreview,
  AgentPreviewMemoryDebug,
  AgentPreviewMemoryPlanEntry,
  AgentPreviewSection,
  PreviewProjectOption,
  PreviewScenario,
  PreviewTaskType,
} from "@/types/agent-preview";
import type { MemoryConfig } from "./components/memory/types";

export interface Agent {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  system_prompt: string;
  primary_model_id: string;
  fallback_models: string[];
  escalation_model_id: string | null;
  strategies: Record<string, unknown>;
  temperature: number;
  thinking_level: string | null;
  verbosity_level: string | null;
  is_active: boolean;
  is_coding_agent: boolean;
  memory_config: (MemoryConfig & Record<string, unknown>) | null;
  effective_memory_config: MemoryConfig & Record<string, unknown>;
  max_concurrency: number | null;
  max_subagent_concurrency: number | null;
  daily_token_budget: number | null;
  hourly_request_limit: number | null;
  timeout_seconds: number | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export type ModelInfo = CatalogModel;

export type TabId =
  | "general"
  | "models"
  | "parameters"
  | "prompts"
  | "memory";
