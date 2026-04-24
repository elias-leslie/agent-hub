/**
 * Model display name lookup for chat-ui package.
 * Single source within this standalone package — avoids duplication
 * across message-utils.ts and hooks/chat-stream/utils.ts.
 */

const MODEL_NAMES: Record<string, string> = {
  "claude-sonnet-4-6": "Claude Sonnet 4.6",
  "claude-opus-4-6": "Claude Opus 4.6",
  "claude-haiku-4-5": "Claude Haiku 4.5",
  "gemini-3-flash-preview": "Gemini 3 Flash",
  "gemini-3-pro-preview": "Gemini 3 Pro",
  "gemini-3.1-pro-preview": "Gemini 3.1 Pro",
  // Short forms (from Claude Code CLI)
  "sonnet-4-6": "Claude Sonnet 4.6",
  "opus-4-6": "Claude Opus 4.6",
  "haiku-4-5": "Claude Haiku 4.5",
  // Legacy display-only (old session data)
  "claude-sonnet-4-5": "Claude Sonnet 4.5",
  "claude-sonnet-4-5-20250514": "Claude Sonnet 4.5",
  "claude-opus-4-5": "Claude Opus 4.5",
  "claude-opus-4-5-20250514": "Claude Opus 4.5",
  "claude-haiku-4-5-20250514": "Claude Haiku 4.5",
};

export function formatModelName(modelId?: string): string {
  if (!modelId) return "Assistant";
  // Strip provider prefixes like "cloudcode/"
  const normalized = modelId.includes("/") ? modelId.split("/").pop()! : modelId;
  return MODEL_NAMES[normalized] || MODEL_NAMES[modelId] || modelId;
}

export const MODEL_ALIAS_ENTRIES: Record<string, { model: string; label: string }> = {
  chat: { model: "chat", label: "Chat" },
  coder: { model: "coder", label: "Coder" },
  planner: { model: "planner", label: "Planner" },
  reasoner: { model: "reasoner", label: "Reasoner" },
  reviewer: { model: "reviewer", label: "Reviewer" },
};
