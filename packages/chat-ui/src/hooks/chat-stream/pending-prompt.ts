/**
 * The server stores a turn's messages when the turn ends, so a session read in the middle of a turn does not show
 * the prompt that started it. The tab that sent the prompt keeps a copy here so that, if it is closed and reopened
 * mid-turn, the reattached answer still sits under the question. Another client attaching sees the answer only.
 * Best effort: storage may be missing or full.
 */

const PREFIX = "agent-hub-chat-ui:pending-prompt:";
const MAX_AGE_MS = 24 * 60 * 60 * 1000;

interface Pending {
  content: string;
  at: number;
}

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function rememberPendingPrompt(sessionId: string, content: string): void {
  try {
    storage()?.setItem(PREFIX + sessionId, JSON.stringify({ content, at: Date.now() } satisfies Pending));
  } catch {
    // best effort
  }
}

export function readPendingPrompt(sessionId: string): string | null {
  try {
    const raw = storage()?.getItem(PREFIX + sessionId);
    if (!raw) return null;
    const pending = JSON.parse(raw) as Pending;
    if (typeof pending.content !== "string" || Date.now() - pending.at > MAX_AGE_MS) {
      clearPendingPrompt(sessionId);
      return null;
    }
    return pending.content;
  } catch {
    return null;
  }
}

export function clearPendingPrompt(sessionId: string): void {
  try {
    storage()?.removeItem(PREFIX + sessionId);
  } catch {
    // best effort
  }
}
