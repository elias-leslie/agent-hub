/**
 * Utility functions for chat streaming.
 */

export { formatModelName } from "../../lib/model-names";

/**
 * Generates a unique message ID.
 */
export function generateId(): string {
  return `msg-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}
