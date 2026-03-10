"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useSessionEvents } from "@/hooks/use-session-events";
import {
  cancelSessionStream,
  fetchSessions,
  type SessionListItem,
} from "@/lib/api/sessions";

const IDLE_POLL_MS = 15_000;
const ACTIVE_POLL_MS = 5_000;

export interface PersonaRuntimeState {
  primarySession: SessionListItem | null;
  activePersonaSessions: SessionListItem[];
  activeChildSessions: SessionListItem[];
  loading: boolean;
  error: string | null;
  stoppingSessionId: string | null;
  refresh: () => Promise<void>;
  stopCurrentStream: () => Promise<boolean>;
}

export function usePersonaRuntime(): PersonaRuntimeState {
  const [activePersonaSessions, setActivePersonaSessions] = useState<SessionListItem[]>([]);
  const [activeChildSessions, setActiveChildSessions] = useState<SessionListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const [stoppingSessionId, setStoppingSessionId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await fetchSessions({ status: "active", page_size: 100 });
      const personaSessions = data.sessions
        .filter((session) => session.agent_slug === "persona")
        .sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at));
      const personaIds = new Set(personaSessions.map((session) => session.id));
      const childSessions = data.sessions
        .filter(
          (session) =>
            session.parent_session_id &&
            personaIds.has(session.parent_session_id) &&
            session.agent_slug !== "persona",
        )
        .sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at));

      setActivePersonaSessions(personaSessions);
      setActiveChildSessions(childSessions);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load Jenny runtime");
    } finally {
      setLoading(false);
    }
  }, []);

  const watchedSessionIds = useMemo(
    () => [...activePersonaSessions, ...activeChildSessions].map((session) => session.id),
    [activePersonaSessions, activeChildSessions],
  );

  useSessionEvents({
    sessionIds: watchedSessionIds,
    autoConnect: true,
    autoReconnect: true,
    onEvent: () => {
      setRefreshTick((value) => value + 1);
    },
  });

  useEffect(() => {
    refresh();
  }, [refresh, refreshTick]);

  useEffect(() => {
    const hasActiveWork = activePersonaSessions.length > 0 || activeChildSessions.length > 0;
    const interval = window.setInterval(
      () => setRefreshTick((value) => value + 1),
      hasActiveWork ? ACTIVE_POLL_MS : IDLE_POLL_MS,
    );
    return () => window.clearInterval(interval);
  }, [activePersonaSessions.length, activeChildSessions.length]);

  const primarySession = useMemo(() => {
    if (activePersonaSessions.length > 0) {
      return activePersonaSessions[0];
    }
    if (activeChildSessions.length > 0) {
      return activeChildSessions[0];
    }
    return null;
  }, [activeChildSessions, activePersonaSessions]);

  const stopCurrentStream = useCallback(async () => {
    if (!primarySession) {
      return false;
    }

    setStoppingSessionId(primarySession.id);
    try {
      const result = await cancelSessionStream(primarySession.id);
      setRefreshTick((value) => value + 1);
      return result.cancelled;
    } finally {
      setStoppingSessionId(null);
    }
  }, [primarySession]);

  return {
    primarySession,
    activePersonaSessions,
    activeChildSessions,
    loading,
    error,
    stoppingSessionId,
    refresh,
    stopCurrentStream,
  };
}
