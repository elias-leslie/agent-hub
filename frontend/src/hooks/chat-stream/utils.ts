/**
 * Utility functions for chat streaming.
 */

/**
 * Maps model IDs to human-readable names.
 */
export function formatModelName(modelId: string): string {
  const modelNames: Record<string, string> = {
    "claude-sonnet-4-5-20250514": "Claude Sonnet 4.5",
    "claude-sonnet-4-5": "Claude Sonnet 4.5",
    "claude-opus-4-6": "Claude Opus 4.6",
    "claude-opus-4-5": "Claude Opus 4.5",
    "claude-opus-4-5-20250514": "Claude Opus 4.5",
    "claude-haiku-4-5-20250514": "Claude Haiku 4.5",
    "claude-haiku-4-5": "Claude Haiku 4.5",
    "gemini-3-flash-preview": "Gemini 3 Flash",
    "gemini-3-pro-preview": "Gemini 3 Pro",
  };
  return modelNames[modelId] || modelId;
}

/**
 * Generates a unique message ID.
 */
export function generateId(): string {
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}
