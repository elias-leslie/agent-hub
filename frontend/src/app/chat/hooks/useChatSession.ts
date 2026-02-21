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
    // Update URL for bookmarking using replaceState instead of router.push
    // to avoid triggering Next.js Suspense re-render, which would remount
    // ChatContent and reinitialize activeSessionId from the URL, wiping
    // in-flight streaming messages.
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", `/chat?session_id=${newSessionId}`);
    }
    setSidebarRefreshTrigger((prev) => prev + 1);
  }, []);

  const handleSelectSession = useCallback((sessionId: string | null) => {
    setActiveSessionId(sessionId);
    setSessionError(null);
    if (sessionId) {
      router.push(`/chat?session_id=${sessionId}`, { scroll: false });
    } else {
      router.push("/chat", { scroll: false });
    }
  }, [router]);

  const handleNewSession = useCallback(() => {
    setActiveSessionId(null);
    setSessionError(null);
    router.push("/chat", { scroll: false });
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
