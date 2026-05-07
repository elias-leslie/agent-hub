/**
 * Model display formatting for chat-ui package.
 * Current names come from /api/models; this fallback only prettifies unknown
 * telemetry ids without maintaining a second model catalog.
 */

export function formatModelName(modelId?: string): string {
  if (!modelId) return "Assistant";
  const normalized = modelId.includes("/") ? modelId.split("/").pop()! : modelId;
  return normalized
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export const MODEL_ALIAS_ENTRIES: Record<string, { model: string; label: string }> = {
  chat: { model: "chat", label: "Chat" },
  coder: { model: "coder", label: "Coder" },
  planner: { model: "planner", label: "Planner" },
  reasoner: { model: "reasoner", label: "Reasoner" },
  reviewer: { model: "reviewer", label: "Reviewer" },
};
