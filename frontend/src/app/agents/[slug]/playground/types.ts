// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

export interface Agent {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  system_prompt: string;
  primary_model_id: string;
  fallback_models: string[];
  temperature: number;
}

export interface AgentPreview {
  slug: string;
  name: string;
  combined_prompt: string;
  mandate_count: number;
  mandate_uuids: string[];
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

export interface DebugTrace {
  model_used: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  mandates_injected: number;
  mandate_uuids: string[];
  combined_prompt_length: number;
}
