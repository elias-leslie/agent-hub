import { useState } from "react";
import { fetchSession, fetchSessionEvents, type Session, type SessionEventsResponse } from "@/lib/api";

export function useSessionExpansion() {
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);
  const [expandedSessionData, setExpandedSessionData] = useState<Session | null>(null);
  const [expandedEventsData, setExpandedEventsData] = useState<SessionEventsResponse | null>(null);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);

  const handleToggleExpand = async (sessionId: string) => {
    if (expandedSessionId === sessionId) {
      setExpandedSessionId(null);
      setExpandedSessionData(null);
      setExpandedEventsData(null);
      return;
    }
    setExpandedSessionId(sessionId);
    setIsLoadingDetails(true);
    try {
      const [sessionData, eventsData] = await Promise.all([
        fetchSession(sessionId),
        fetchSessionEvents(sessionId, { page_size: 500 }),
      ]);
      setExpandedSessionData(sessionData);
      setExpandedEventsData(eventsData);
    } catch {
      setExpandedSessionData(null);
      setExpandedEventsData(null);
    } finally {
      setIsLoadingDetails(false);
    }
  };

  const clearExpansion = () => {
    setExpandedSessionId(null);
    setExpandedSessionData(null);
  };

  return {
    expandedSessionId,
    expandedSessionData,
    expandedEventsData,
    isLoadingDetails,
    handleToggleExpand,
    clearExpansion,
  };
}
