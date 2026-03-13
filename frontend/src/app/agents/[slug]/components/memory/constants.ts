import { MemoryConfig } from "./types";

export const DEFAULT_CONFIG: MemoryConfig = {
  injection_enabled: true,
  include_mandates: true,
  include_guardrails: true,
  include_references: true,
  continuity_enabled: true,
  continuity_max_sessions: 5,
  audience_tags: [],
  exclude_tags: [],
};
