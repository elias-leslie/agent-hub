import { useRef, useState } from "react";
import { fetchAllSessionEvents, fetchSession, type Session, type SessionEventsResponse } from "@/lib/api";

export function useSessionExpansion() {
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);
  const [expandedSessionData, setExpandedSessionData] = useState<Session | null>(null);
  const [expandedEventsData, setExpandedEventsData] = useState<SessionEventsResponse | null>(null);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);
  const requestSequenceRef = useRef(0);

  const handleToggleExpand = async (sessionId: string) => {
    if (expandedSessionId === sessionId) {
      requestSequenceRef.current += 1;
      setExpandedSessionId(null);
      setExpandedSessionData(null);
      setExpandedEventsData(null);
      setIsLoadingDetails(false);
      return;
    }

    const requestId = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestId;
    setExpandedSessionId(sessionId);
    setExpandedSessionData(null);
    setExpandedEventsData(null);
    setIsLoadingDetails(true);

    try {
      const [sessionData, eventsData] = await Promise.all([
        fetchSession(sessionId),
        fetchAllSessionEvents(sessionId, { page_size: 500 }),
      ]);

      if (requestSequenceRef.current !== requestId) {
        return;
      }

      setExpandedSessionData(sessionData);
      setExpandedEventsData(eventsData);
    } catch {
      if (requestSequenceRef.current !== requestId) {
        return;
      }

      setExpandedSessionData(null);
      setExpandedEventsData(null);
    } finally {
      if (requestSequenceRef.current === requestId) {
        setIsLoadingDetails(false);
      }
    }
  };

  const clearExpansion = () => {
    requestSequenceRef.current += 1;
    setExpandedSessionId(null);
    setExpandedSessionData(null);
    setExpandedEventsData(null);
    setIsLoadingDetails(false);
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
