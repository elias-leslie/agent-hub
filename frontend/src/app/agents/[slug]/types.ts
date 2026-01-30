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
  is_active: boolean;
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

export type TabId = "general" | "models" | "prompt" | "parameters";
