import type { CatalogModel } from "@/lib/models";

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

export interface AgentPreview {
  slug: string;
  name: string;
  combined_prompt: string;
  mandate_count: number;
  guardrail_count: number;
  mandate_uuids: string[];
  guardrail_uuids: string[];
  task_type?: PreviewTaskType | null;
  phase?: string | null;
  project_id?: string | null;
  task_prompt?: string | null;
  sections: AgentPreviewSection[];
}

export type PreviewTaskType = "chat" | "heartbeat" | "wake" | "review";

export interface AgentPreviewSection {
  label: string;
  source_kind: string;
  source_id: string;
  role?: string | null;
  priority?: number | null;
  updated_at?: string | null;
  content_hash: string;
  chars: number;
  estimated_tokens: number;
  content: string;
}

export type ModelInfo = CatalogModel;

export type TabId =
  | "general"
  | "models"
  | "parameters"
  | "permissions"
  | "prompts"
  | "memory";
