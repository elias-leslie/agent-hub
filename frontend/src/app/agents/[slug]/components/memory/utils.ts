import { MemoryConfig } from "./types";

const DEFAULT_MEMORY_CONFIG: MemoryConfig = {
  injection_enabled: true,
  include_mandates: true,
  include_guardrails: true,
  include_references: true,
  continuity_enabled: true,
  continuity_max_sessions: 5,
  audience_tags: [],
  exclude_tags: [],
};

const KNOWN_KEYS = new Set([
  "enabled",
  "injection_enabled",
  "include_mandates",
  "include_guardrails",
  "include_references",
  "continuity_enabled",
  "continuity_max_sessions",
  "audience_tags",
  "exclude_tags",
]);

function parseStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === "string")
    .map((item) => item.trim())
    .filter((item, index, items) => item.length > 0 && items.indexOf(item) === index);
}

export function createDefaultConfig(): MemoryConfig {
  return {
    ...DEFAULT_MEMORY_CONFIG,
    audience_tags: [...DEFAULT_MEMORY_CONFIG.audience_tags],
    exclude_tags: [...DEFAULT_MEMORY_CONFIG.exclude_tags],
  };
}

export function parseConfig(raw: Record<string, unknown> | null): MemoryConfig {
  if (!raw) return createDefaultConfig();
  const enabled = typeof raw.enabled === "boolean" ? raw.enabled : true;
  const injectionEnabled =
    typeof raw.injection_enabled === "boolean" ? raw.injection_enabled : true;
  const memoryInjectionEnabled = enabled && injectionEnabled;
  const extras = Object.fromEntries(
    Object.entries(raw).filter(([key]) => !KNOWN_KEYS.has(key))
  );
  return {
    ...extras,
    injection_enabled: memoryInjectionEnabled,
    include_mandates:
      memoryInjectionEnabled &&
      (typeof raw.include_mandates === "boolean" ? raw.include_mandates : true),
    include_guardrails:
      memoryInjectionEnabled &&
      (typeof raw.include_guardrails === "boolean"
        ? raw.include_guardrails
        : true),
    include_references:
      memoryInjectionEnabled &&
      (typeof raw.include_references === "boolean"
        ? raw.include_references
        : true),
    continuity_enabled:
      memoryInjectionEnabled &&
      (typeof raw.continuity_enabled === "boolean"
        ? raw.continuity_enabled
        : true),
    continuity_max_sessions:
      typeof raw.continuity_max_sessions === "number" &&
      Number.isInteger(raw.continuity_max_sessions) &&
      raw.continuity_max_sessions >= 1
        ? raw.continuity_max_sessions
        : 5,
    audience_tags: parseStringArray(raw.audience_tags),
    exclude_tags: parseStringArray(raw.exclude_tags),
  };
}

export function parseTagsFromInput(value: string): string[] {
  return value
    .split(",")
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
}
