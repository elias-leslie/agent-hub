import { Agent } from "../../types";

export interface MemoryTabProps {
  formData: Partial<Agent>;
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void;
}

export interface MemoryConfig extends Record<string, unknown> {
  injection_enabled: boolean;
  include_mandates: boolean;
  include_guardrails: boolean;
  include_references: boolean;
  continuity_enabled: boolean;
  continuity_max_sessions: number;
  audience_tags: string[];
  exclude_tags: string[];
}
