import { MemoryConfig } from "./types";

export const DEFAULT_CONFIG: MemoryConfig = {
  injection_enabled: true,
  budget_enforcement: true,
  token_budget: 3500,
  max_mandates: 0,
  max_guardrails: 0,
  reference_index: true,
  continuity_enabled: true,
  continuity_max_sessions: 5,
  include_tags: [],
  exclude_tags: [],
};
