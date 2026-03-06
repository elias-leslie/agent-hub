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
  premium_model_id: string | null;
  strategies: Record<string, unknown>;
  temperature: number;
  thinking_level: string | null;
  verbosity_level: string | null;
  is_active: boolean;
  is_coding_agent: boolean;
  tool_permissions: PermissionConfig | null;
  memory_config: Record<string, unknown> | null;
  timeout_seconds?: number;
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
}

export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
}

export type TabId =
  | "general"
  | "models"
  | "prompt"
  | "parameters"
  | "permissions"
  | "prompts"
  | "memory";
