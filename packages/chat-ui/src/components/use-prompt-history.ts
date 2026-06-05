"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const HISTORY_KEY_PREFIX = "agent_hub_prompt_history";
const HISTORY_LIMIT = 50;

function storageKeyFor(agentSlug?: string | null): string {
  return `${HISTORY_KEY_PREFIX}:${agentSlug || "_default"}`;
}

function loadHistory(storageKey: string): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((e): e is string => typeof e === "string" && e.length > 0)
      .slice(0, HISTORY_LIMIT);
  } catch {
    return [];
  }
}

function saveHistory(storageKey: string, history: string[]): void {
  if (typeof window === "undefined") return;
  try {
    if (history.length > 0) {
      window.localStorage.setItem(storageKey, JSON.stringify(history));
    } else {
      window.localStorage.removeItem(storageKey);
    }
  } catch {
    // ignore quota / serialization errors — history is best-effort
  }
}

/**
 * Shell-style recall of recently sent prompts, persisted in localStorage and
 * scoped per agent (`agentSlug`). `history[0]` is the most recent. The browsing
 * cursor is -1 when the user is editing a fresh draft (not browsing history).
 * Stepping past the newest entry restores the stashed draft, mirroring terminal
 * up/down history behaviour.
 */
export function usePromptHistory(agentSlug?: string | null) {
  const storageKey = storageKeyFor(agentSlug);
  const [history, setHistory] = useState<string[]>(() => loadHistory(storageKey));
  const indexRef = useRef(-1);
  const draftRef = useRef("");

  // Reload (and stop browsing) when the agent — and thus the storage key —
  // changes, so each agent recalls only its own prompts.
  useEffect(() => {
    setHistory(loadHistory(storageKey));
    indexRef.current = -1;
    draftRef.current = "";
  }, [storageKey]);

  const record = useCallback(
    (entry: string) => {
      const trimmed = entry.trim();
      if (!trimmed) return;
      setHistory((prev) => {
        const next = [trimmed, ...prev.filter((e) => e !== trimmed)].slice(
          0,
          HISTORY_LIMIT,
        );
        saveHistory(storageKey, next);
        return next;
      });
      indexRef.current = -1;
      draftRef.current = "";
    },
    [storageKey],
  );

  /** Stop browsing — call when the user edits the input directly. */
  const resetCursor = useCallback(() => {
    indexRef.current = -1;
  }, []);

  /** Step to an older entry. Returns recalled text, or null if no history. */
  const recallPrevious = useCallback(
    (currentInput: string): string | null => {
      if (history.length === 0) return null;
      if (indexRef.current === -1) draftRef.current = currentInput;
      indexRef.current = Math.min(indexRef.current + 1, history.length - 1);
      return history[indexRef.current];
    },
    [history],
  );

  /** Step to a newer entry; past the newest restores the stashed draft. */
  const recallNext = useCallback((): string | null => {
    if (indexRef.current === -1) return null;
    const nextIndex = indexRef.current - 1;
    if (nextIndex < 0) {
      indexRef.current = -1;
      return draftRef.current;
    }
    indexRef.current = nextIndex;
    return history[nextIndex];
  }, [history]);

  return { record, resetCursor, recallPrevious, recallNext };
}
