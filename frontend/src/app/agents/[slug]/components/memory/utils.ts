import { MemoryConfig } from "./types";
import { DEFAULT_CONFIG } from "./constants";

export function parseConfig(raw: Record<string, unknown> | null): MemoryConfig {
  if (!raw) return { ...DEFAULT_CONFIG };
  return {
    injection_enabled:
      (raw.injection_enabled as boolean | undefined) ??
      (raw.enabled as boolean | undefined) ??
      true,
    include_mandates: (raw.include_mandates as boolean | undefined) ?? true,
    include_guardrails: (raw.include_guardrails as boolean | undefined) ?? true,
    include_references: (raw.include_references as boolean | undefined) ?? true,
    continuity_enabled: (raw.continuity_enabled as boolean) ?? true,
    continuity_max_sessions: (raw.continuity_max_sessions as number) ?? 5,
    audience_tags:
      (raw.audience_tags as string[] | undefined) ??
      (raw.include_tags as string[] | undefined) ??
      [],
    exclude_tags: (raw.exclude_tags as string[]) ?? [],
  };
}

export function parseTagsFromInput(value: string): string[] {
  return value
    .split(",")
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
}
