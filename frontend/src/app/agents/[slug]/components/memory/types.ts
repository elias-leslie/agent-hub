import { Agent } from "../../types";

export interface MemoryTabProps {
  formData: Partial<Agent>;
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void;
}

export interface MemoryConfig {
  injection_enabled: boolean;
  budget_enforcement: boolean;
  token_budget: number;
  max_mandates: number;
  max_guardrails: number;
  reference_index: boolean;
  continuity_enabled: boolean;
  continuity_max_sessions: number;
  include_tags: string[];
  exclude_tags: string[];
}
