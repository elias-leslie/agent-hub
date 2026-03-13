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

export interface ToolPermission {
  name: string;
  allowed: boolean;
  requires_confirmation: boolean;
}

export interface PermissionConfig {
  mode: "yolo" | "ask" | "granular";
  tool_permissions: Record<string, ToolPermission>;
  allow_list: string[];
  deny_list: string[];
}

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
  tool_permissions: PermissionConfig | null;
  memory_config: Record<string, unknown> | null;
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
  | "permissions"
  | "prompts"
  | "memory";
