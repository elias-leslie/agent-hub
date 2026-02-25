import { useState, useCallback, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";

const STORAGE_PREFIX = "persona_active_session_id";
const LEGACY_STORAGE_KEY = "persona_active_session_id";

function storageKey(projectId: string): string {
  return `${STORAGE_PREFIX}:${projectId}`;
}

function getStoredSessionId(projectId: string): string | null {
  if (typeof window === "undefined") return null;
  const value = localStorage.getItem(storageKey(projectId));
  if (value) return value;
  // Migrate legacy single key to per-project key for agent-hub
  if (projectId === "agent-hub") {
    const legacy = localStorage.getItem(LEGACY_STORAGE_KEY);
    if (legacy) {
      localStorage.setItem(storageKey(projectId), legacy);
      localStorage.removeItem(LEGACY_STORAGE_KEY);
      return legacy;
    }
  }
  return null;
}

function storeSessionId(projectId: string, sessionId: string | null): void {
  if (typeof window === "undefined") return;
  if (sessionId) {
    localStorage.setItem(storageKey(projectId), sessionId);
  } else {
    localStorage.removeItem(storageKey(projectId));
  }
}

interface UseChatSessionReturn {
  activeSessionId: string | null;
  sidebarRefreshTrigger: number;
  sessionError: string | null;
  setSessionError: (error: string | null) => void;
  handleSessionCreated: (newSessionId: string) => void;
  handleSelectSession: (sessionId: string | null) => void;
  handleNewSession: () => void;
}

export function useChatSession(projectId = "agent-hub"): UseChatSessionReturn {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sessionIdFromUrl = searchParams.get("session_id");
  const prevProjectId = useRef(projectId);

  // Priority: URL param > localStorage
  const [activeSessionId, setActiveSessionId] = useState<string | null>(
    sessionIdFromUrl || getStoredSessionId(projectId)
  );
  const [sidebarRefreshTrigger, setSidebarRefreshTrigger] = useState(0);
  const [sessionError, setSessionError] = useState<string | null>(null);

  // When projectId changes, restore that project's last session
  useEffect(() => {
    if (prevProjectId.current === projectId) return;
    prevProjectId.current = projectId;
    const stored = getStoredSessionId(projectId);
    setActiveSessionId(stored);
    setSessionError(null);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      if (stored) {
        url.searchParams.set("session_id", stored);
      } else {
        url.searchParams.delete("session_id");
      }
      window.history.replaceState(null, "", url.toString());
    }
  }, [projectId]);

  const handleSessionCreated = useCallback((newSessionId: string) => {
    setActiveSessionId(newSessionId);
    storeSessionId(projectId, newSessionId);
    // Update URL for bookmarking using replaceState instead of router.push
    // to avoid triggering Next.js Suspense re-render, which would remount
    // ChatContent and reinitialize activeSessionId from the URL, wiping
    // in-flight streaming messages.
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.set("session_id", newSessionId);
      window.history.replaceState(null, "", url.toString());
    }
    setSidebarRefreshTrigger((prev) => prev + 1);
  }, [projectId]);

  const handleSelectSession = useCallback((sessionId: string | null) => {
    setActiveSessionId(sessionId);
    storeSessionId(projectId, sessionId);
    setSessionError(null);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      if (sessionId) {
        url.searchParams.set("session_id", sessionId);
      } else {
        url.searchParams.delete("session_id");
      }
      router.push(url.pathname + url.search, { scroll: false });
    }
  }, [router, projectId]);

  const handleNewSession = useCallback(() => {
    setActiveSessionId(null);
    storeSessionId(projectId, null);
    setSessionError(null);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.delete("session_id");
      router.push(url.pathname + url.search, { scroll: false });
    }
  }, [router, projectId]);

  return {
    activeSessionId,
    sidebarRefreshTrigger,
    sessionError,
    setSessionError,
    handleSessionCreated,
    handleSelectSession,
    handleNewSession,
  };
}
