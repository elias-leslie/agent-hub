import { Agent } from "../../types";

export interface MemoryTabProps {
  formData: Partial<Agent>;
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void;
}

export interface MemoryConfig extends Record<string, unknown> {
  injection_enabled: boolean;
  project_index_enabled: boolean;
  tool_capabilities_enabled: boolean;
  include_mandates: boolean;
  include_guardrails: boolean;
  include_references: boolean;
  reference_index_enabled: boolean;
  continuity_enabled: boolean;
  continuity_max_sessions: number;
  audience_tags: string[];
  exclude_tags: string[];
  exclude_memory_uuids: string[];
  consumer_profile?: string;
  runtime_consumer_profile?: string;
  preview_consumer_profile?: string;
}
