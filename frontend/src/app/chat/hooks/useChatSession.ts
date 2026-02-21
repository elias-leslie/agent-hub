import { useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";

interface UseChatSessionReturn {
  activeSessionId: string | null;
  sidebarRefreshTrigger: number;
  sessionError: string | null;
  setSessionError: (error: string | null) => void;
  handleSessionCreated: (newSessionId: string) => void;
  handleSelectSession: (sessionId: string | null) => void;
  handleNewSession: () => void;
}

export function useChatSession(): UseChatSessionReturn {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sessionIdFromUrl = searchParams.get("session_id");
  
  const [activeSessionId, setActiveSessionId] = useState<string | null>(sessionIdFromUrl);
  const [sidebarRefreshTrigger, setSidebarRefreshTrigger] = useState(0);
  const [sessionError, setSessionError] = useState<string | null>(null);

  const handleSessionCreated = useCallback((newSessionId: string) => {
    // Persist session ID in React state so subsequent messages reuse this
    // session instead of creating new one-shot sessions each time.
    setActiveSessionId(newSessionId);
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
  }, []);

  const handleSelectSession = useCallback((sessionId: string | null) => {
    setActiveSessionId(sessionId);
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
  }, [router]);

  const handleNewSession = useCallback(() => {
    setActiveSessionId(null);
    setSessionError(null);
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      url.searchParams.delete("session_id");
      router.push(url.pathname + url.search, { scroll: false });
    }
  }, [router]);

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
