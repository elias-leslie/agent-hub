import { MemoryConfig } from "./types";
import { DEFAULT_CONFIG } from "./constants";

export function parseConfig(raw: Record<string, unknown> | null): MemoryConfig {
  if (!raw) return { ...DEFAULT_CONFIG };
  return {
    injection_enabled: (raw.injection_enabled as boolean) ?? true,
    budget_enforcement: (raw.budget_enforcement as boolean) ?? true,
    token_budget: (raw.token_budget as number) ?? 3500,
    max_mandates: (raw.max_mandates as number) ?? 0,
    max_guardrails: (raw.max_guardrails as number) ?? 0,
    reference_index: (raw.reference_index as boolean) ?? true,
    continuity_enabled: (raw.continuity_enabled as boolean) ?? true,
    continuity_max_sessions: (raw.continuity_max_sessions as number) ?? 5,
    include_tags: (raw.include_tags as string[]) ?? [],
    exclude_tags: (raw.exclude_tags as string[]) ?? [],
  };
}

export function parseTagsFromInput(value: string): string[] {
  return value
    .split(",")
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
}
