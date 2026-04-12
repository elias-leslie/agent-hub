import { MemoryConfig } from "./types";

const KNOWN_KEYS = new Set([
  "enabled",
  "injection_enabled",
  "project_index_enabled",
  "tool_capabilities_enabled",
  "include_mandates",
  "include_guardrails",
  "include_references",
  "reference_index_enabled",
  "continuity_enabled",
  "continuity_max_sessions",
  "audience_tags",
  "exclude_tags",
  "exclude_memory_uuids",
  "consumer_profile",
  "runtime_consumer_profile",
  "preview_consumer_profile",
]);

function parseBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function parseInteger(value: unknown, fallback: number): number {
  return typeof value === "number" &&
    Number.isInteger(value) &&
    value >= 1
    ? value
    : fallback;
}

function parseStringArray(value: unknown, fallback: string[]): string[] {
  if (!Array.isArray(value)) return [...fallback];
  return value
    .filter((item): item is string => typeof item === "string")
    .map((item) => item.trim())
    .filter((item, index, items) => item.length > 0 && items.indexOf(item) === index);
}

function parseOptionalString(value: unknown, fallback?: string): string | undefined {
  if (typeof value !== "string") return fallback;
  const cleaned = value.trim();
  return cleaned.length > 0 ? cleaned : undefined;
}

export function cloneConfig<T extends MemoryConfig>(config: T): T {
  return {
    ...config,
    audience_tags: [...config.audience_tags],
    exclude_tags: [...config.exclude_tags],
    exclude_memory_uuids: [...config.exclude_memory_uuids],
  };
}

export function parseConfig(
  raw: Record<string, unknown>,
  fallback: MemoryConfig
): MemoryConfig {
  const enabled = parseBoolean(raw.enabled, true);
  const memoryInjectionEnabled =
    enabled &&
    parseBoolean(raw.injection_enabled, fallback.injection_enabled);
  const extras = Object.fromEntries(
    Object.entries(raw).filter(([key]) => !KNOWN_KEYS.has(key))
  );
  return {
    ...cloneConfig(fallback),
    ...extras,
    injection_enabled: memoryInjectionEnabled,
    project_index_enabled: parseBoolean(
      raw.project_index_enabled,
      fallback.project_index_enabled
    ),
    tool_capabilities_enabled: parseBoolean(
      raw.tool_capabilities_enabled,
      fallback.tool_capabilities_enabled
    ),
    include_mandates:
      memoryInjectionEnabled &&
      parseBoolean(raw.include_mandates, fallback.include_mandates),
    include_guardrails:
      memoryInjectionEnabled &&
      parseBoolean(raw.include_guardrails, fallback.include_guardrails),
    include_references:
      memoryInjectionEnabled &&
      parseBoolean(raw.include_references, fallback.include_references),
    reference_index_enabled:
      memoryInjectionEnabled &&
      parseBoolean(raw.reference_index_enabled, fallback.reference_index_enabled),
    continuity_enabled:
      memoryInjectionEnabled &&
      parseBoolean(raw.continuity_enabled, fallback.continuity_enabled),
    continuity_max_sessions: parseInteger(
      raw.continuity_max_sessions,
      fallback.continuity_max_sessions
    ),
    audience_tags: parseStringArray(raw.audience_tags, fallback.audience_tags),
    exclude_tags: parseStringArray(raw.exclude_tags, fallback.exclude_tags),
    exclude_memory_uuids: parseStringArray(
      raw.exclude_memory_uuids,
      fallback.exclude_memory_uuids
    ),
    consumer_profile: parseOptionalString(
      raw.consumer_profile,
      fallback.consumer_profile
    ),
    runtime_consumer_profile: parseOptionalString(
      raw.runtime_consumer_profile,
      fallback.runtime_consumer_profile
    ),
    preview_consumer_profile: parseOptionalString(
      raw.preview_consumer_profile,
      fallback.preview_consumer_profile
    ),
  };
}

export function parseTagsFromInput(value: string): string[] {
  return value
    .split(",")
    .map((t) => t.trim())
    .filter((t) => t.length > 0);
}
