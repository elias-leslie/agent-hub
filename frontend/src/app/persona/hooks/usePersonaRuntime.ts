"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useSessionEvents } from "@/hooks/use-session-events";
import type { SessionEvent } from "@/types/events";
import {
  cancelSessionStream,
  fetchSessions,
  type SessionListItem,
} from "@/lib/api/sessions";

const IDLE_POLL_MS = 15_000;
const ACTIVE_POLL_MS = 5_000;

function truncateText(value: string, maxLength = 96): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 1)}…`;
}

function patchSessionWithLiveEvent(session: SessionListItem, event: SessionEvent): SessionListItem {
  const liveActivity = { ...(session.live_activity ?? {}) };
  liveActivity.last_event_at = event.timestamp;
  liveActivity.last_model_activity_at = event.timestamp;

  if (event.event_type === "message") {
    const content =
      typeof event.data === "object" && event.data && "content" in event.data && typeof event.data.content === "string"
        ? event.data.content
        : null;
    const role =
      typeof event.data === "object" && event.data && "role" in event.data && typeof event.data.role === "string"
        ? event.data.role
        : null;
    liveActivity.phase = role === "assistant" ? "finalizing" : "waiting_for_model";
    liveActivity.status = "active";
    liveActivity.summary = content ? truncateText(content) : "New message";
    liveActivity.last_event_type = role ? `${role}_message` : "message";
  } else if (event.event_type === "tool_use") {
    const toolName =
      typeof event.data === "object" && event.data && "tool_name" in event.data && typeof event.data.tool_name === "string"
        ? event.data.tool_name
        : "tool";
    liveActivity.phase = "running_tool";
    liveActivity.status = "active";
    liveActivity.summary = `Running ${toolName}`;
    liveActivity.current_tool_name = toolName;
    liveActivity.last_tool_name = toolName;
    liveActivity.last_tool_started_at = event.timestamp;
    liveActivity.last_event_type = "tool_use";
  } else if (event.event_type === "tool_result") {
    const toolName =
      typeof event.data === "object" && event.data && "tool_name" in event.data && typeof event.data.tool_name === "string"
        ? event.data.tool_name
        : liveActivity.last_tool_name;
    const toolOutput =
      typeof event.data === "object" && event.data && "tool_output" in event.data && typeof event.data.tool_output === "object"
        ? event.data.tool_output
        : null;
    const resultContent =
      toolOutput && "content" in toolOutput && typeof toolOutput.content === "string"
        ? toolOutput.content
        : null;
    const isError =
      typeof event.data === "object" && event.data && "is_error" in event.data && typeof event.data.is_error === "boolean"
        ? event.data.is_error
        : toolOutput && "is_error" in toolOutput && typeof toolOutput.is_error === "boolean"
          ? toolOutput.is_error
          : false;
    liveActivity.phase = "waiting_for_model";
    liveActivity.status = "active";
    liveActivity.summary = isError
      ? `Tool failed: ${toolName || "tool"}`
      : resultContent
        ? truncateText(resultContent)
        : `Waiting for model after ${toolName || "tool"}`;
    liveActivity.current_tool_name = null;
    liveActivity.last_tool_name = toolName ?? null;
    liveActivity.last_tool_finished_at = event.timestamp;
    liveActivity.last_tool_error = isError;
    liveActivity.last_event_type = "tool_result";
  } else if (event.event_type === "complete") {
    liveActivity.phase = "completed";
    liveActivity.status = "completed";
    liveActivity.summary = "Execution completed";
    liveActivity.current_tool_name = null;
    liveActivity.last_event_type = "complete";
  } else if (event.event_type === "error") {
    const errorMessage =
      typeof event.data === "object" && event.data && "error_message" in event.data && typeof event.data.error_message === "string"
        ? event.data.error_message
        : "Session error";
    liveActivity.phase = "error";
    liveActivity.status = "error";
    liveActivity.summary = `Error: ${truncateText(errorMessage, 88)}`;
    liveActivity.current_tool_name = null;
    liveActivity.last_event_type = "error";
  } else if (event.event_type === "session_start") {
    liveActivity.phase = "waiting_for_model";
    liveActivity.status = "active";
    liveActivity.summary = "Session started";
    liveActivity.last_event_type = "session_start";
  }

  return {
    ...session,
    updated_at: event.timestamp,
    status:
      event.event_type === "complete"
        ? "completed"
        : event.event_type === "error"
          ? "failed"
          : session.status,
    live_activity: liveActivity as SessionListItem["live_activity"],
  };
}

function patchSessionList(sessions: SessionListItem[], event: SessionEvent): SessionListItem[] {
  let changed = false;
  const patched = sessions.map((session) => {
    if (session.id !== event.session_id) {
      return session;
    }
    changed = true;
    return patchSessionWithLiveEvent(session, event);
  });
  return changed
    ? [...patched].sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at))
    : sessions;
}

export interface PersonaRuntimeState {
  primarySession: SessionListItem | null;
  activePersonaSessions: SessionListItem[];
  activeChildSessions: SessionListItem[];
  loading: boolean;
  error: string | null;
  stoppingSessionId: string | null;
  runtimeSyncKey: string;
  refresh: () => Promise<void>;
  stopCurrentStream: () => Promise<boolean>;
  stopActiveWork: () => Promise<{ cancelled: number; attempted: number }>;
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
      setError(err instanceof Error ? err.message : "Failed to load persona runtime");
    } finally {
      setLoading(false);
    }
  }, []);

  const watchedSessionIds = useMemo(
    () => [...activePersonaSessions, ...activeChildSessions].map((session) => session.id),
    [activePersonaSessions, activeChildSessions],
  );

  const { status: liveEventsStatus } = useSessionEvents({
    sessionIds: watchedSessionIds,
    autoConnect: true,
    autoReconnect: true,
    onEvent: (event) => {
      let matched = false;
      setActivePersonaSessions((current) => {
        const next = patchSessionList(current, event);
        matched = matched || next !== current;
        return next;
      });
      setActiveChildSessions((current) => {
        const next = patchSessionList(current, event);
        matched = matched || next !== current;
        return next;
      });
      if (!matched) {
        setRefreshTick((value) => value + 1);
        return;
      }
      if (event.event_type === "complete" || event.event_type === "error" || event.event_type === "session_start") {
        window.setTimeout(() => {
          setRefreshTick((value) => value + 1);
        }, 700);
      }
    },
  });

  useEffect(() => {
    refresh();
  }, [refresh, refreshTick]);

  useEffect(() => {
    const hasActiveWork = activePersonaSessions.length > 0 || activeChildSessions.length > 0;
    if (hasActiveWork && liveEventsStatus === "connected") {
      return;
    }
    const interval = window.setInterval(
      () => setRefreshTick((value) => value + 1),
      hasActiveWork ? ACTIVE_POLL_MS : IDLE_POLL_MS,
    );
    return () => window.clearInterval(interval);
  }, [activePersonaSessions.length, activeChildSessions.length, liveEventsStatus]);

  const primarySession = useMemo(() => {
    if (activePersonaSessions.length > 0) {
      return activePersonaSessions[0];
    }
    if (activeChildSessions.length > 0) {
      return activeChildSessions[0];
    }
    return null;
  }, [activeChildSessions, activePersonaSessions]);

  const runtimeSyncKey = useMemo(() => {
    const personaKey = activePersonaSessions.map((session) => `${session.id}:${session.updated_at}`).join("|");
    const childKey = activeChildSessions.map((session) => `${session.id}:${session.updated_at}`).join("|");
    return `${personaKey}::${childKey}`;
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

  const stopActiveWork = useCallback(async () => {
    const activeSessions = [...activePersonaSessions, ...activeChildSessions].filter(
      (session) =>
        session.status === "active"
        || session.live_activity?.status === "active"
        || session.live_activity?.phase === "running_tool"
        || session.live_activity?.phase === "waiting_for_model",
    );
    if (activeSessions.length === 0) {
      return { cancelled: 0, attempted: 0 };
    }

    setStoppingSessionId(activeSessions[0]?.id ?? null);
    try {
      const results = await Promise.all(
        activeSessions.map(async (session) => {
          try {
            const result = await cancelSessionStream(session.id);
            return result.cancelled ? 1 : 0;
          } catch {
            return 0;
          }
        }),
      );
      setRefreshTick((value) => value + 1);
      return {
        cancelled: results.reduce<number>((sum, value) => sum + value, 0),
        attempted: activeSessions.length,
      };
    } finally {
      setStoppingSessionId(null);
    }
  }, [activeChildSessions, activePersonaSessions]);

  return {
    primarySession,
    activePersonaSessions,
    activeChildSessions,
    loading,
    error,
    stoppingSessionId,
    runtimeSyncKey,
    refresh,
    stopCurrentStream,
    stopActiveWork,
  };
}
