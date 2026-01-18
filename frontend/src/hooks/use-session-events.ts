"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getWsUrl } from "@/lib/api-config";
import type {
  ConnectionStatus,
  SessionEvent,
  SessionEventType,
  SubscribeRequest,
  SubscribeResponse,
} from "@/types/events";

const MAX_RECONNECT_DELAY = 30000;
const INITIAL_RECONNECT_DELAY = 1000;

interface UseSessionEventsOptions {
  /** Session IDs to filter (empty = all sessions) */
  sessionIds?: string[];
  /** Event types to filter (empty = all types) */
  eventTypes?: SessionEventType[];
  /** Callback when event received */
  onEvent?: (event: SessionEvent) => void;
  /** Auto-connect on mount */
  autoConnect?: boolean;
  /** Enable reconnection on disconnect */
  autoReconnect?: boolean;
}

interface UseSessionEventsReturn {
  /** Recent events (last 100) */
  events: SessionEvent[];
  /** Connection status */
  status: ConnectionStatus;
  /** Error message if any */
  error: string | null;
  /** Subscription ID if connected */
  subscriptionId: string | null;
  /** Connect to WebSocket */
  connect: () => void;
  /** Disconnect from WebSocket */
  disconnect: () => void;
  /** Update subscription filters */
  updateFilters: (
    sessionIds?: string[],
    eventTypes?: SessionEventType[],
  ) => void;
  /** Clear event history */
  clearEvents: () => void;
}

/**
 * Hook for subscribing to real-time session events via WebSocket.
 *
 * @example
 * // Subscribe to all events
 * const { events, status, connect } = useSessionEvents();
 *
 * @example
 * // Subscribe to specific session
 * const { events } = useSessionEvents({
 *   sessionIds: ["abc-123"],
 *   eventTypes: ["message", "complete"],
 *   onEvent: (e) => console.log("Event:", e),
 * });
 */
export function useSessionEvents(
  options: UseSessionEventsOptions = {},
): UseSessionEventsReturn {
  const {
    sessionIds = [],
    eventTypes = [],
    onEvent,
    autoConnect = true,
    autoReconnect = true,
  } = options;

  const [events, setEvents] = useState<SessionEvent[]>([]);
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [error, setError] = useState<string | null>(null);
  const [subscriptionId, setSubscriptionId] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectDelayRef = useRef(INITIAL_RECONNECT_DELAY);
  const shouldReconnectRef = useRef(autoReconnect);
  const filtersRef = useRef({ sessionIds, eventTypes });
  const onEventRef = useRef(onEvent);
  const connectRef = useRef<() => void>(() => {});

  // Keep refs in sync
  useEffect(() => {
    filtersRef.current = { sessionIds, eventTypes };
  }, [sessionIds, eventTypes]);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  const scheduleReconnect = useCallback(() => {
    if (!shouldReconnectRef.current) return;

    clearReconnectTimeout();
    const delay = reconnectDelayRef.current;
    reconnectDelayRef.current = Math.min(delay * 2, MAX_RECONNECT_DELAY);

    reconnectTimeoutRef.current = setTimeout(() => {
      if (shouldReconnectRef.current) {
        connectRef.current();
      }
    }, delay);
  }, [clearReconnectTimeout]);

  const connect = useCallback(() => {
    // Clean up existing connection
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    clearReconnectTimeout();

    setError(null);
    setStatus("connecting");
    shouldReconnectRef.current = autoReconnect;

    const ws = new WebSocket(getWsUrl("/api/events"));
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus("connected");
      reconnectDelayRef.current = INITIAL_RECONNECT_DELAY;

      // Send subscribe message
      const request: SubscribeRequest = {
        type: "subscribe",
        session_ids:
          filtersRef.current.sessionIds.length > 0
            ? filtersRef.current.sessionIds
            : undefined,
        event_types:
          filtersRef.current.eventTypes.length > 0
            ? filtersRef.current.eventTypes
            : undefined,
      };
      ws.send(JSON.stringify(request));
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        // Handle subscription responses
        if ("type" in data && !("event_type" in data)) {
          const response = data as SubscribeResponse;
          if (response.type === "subscribed" || response.type === "updated") {
            setSubscriptionId(response.subscription_id ?? null);
          } else if (response.type === "error") {
            setError(response.message ?? "Subscription error");
          }
          return;
        }

        // Handle session events
        if ("event_type" in data) {
          const sessionEvent = data as SessionEvent;
          setEvents((prev) => {
            const updated = [...prev, sessionEvent];
            // Keep last 100 events
            return updated.slice(-100);
          });
          onEventRef.current?.(sessionEvent);
        }
      } catch {
        console.error("Failed to parse WebSocket message:", event.data);
      }
    };

    ws.onerror = () => {
      setError("WebSocket connection error");
      setStatus("error");
    };

    ws.onclose = () => {
      wsRef.current = null;
      setSubscriptionId(null);

      if (shouldReconnectRef.current) {
        setStatus("connecting");
        scheduleReconnect();
      } else {
        setStatus("disconnected");
      }
    };
  }, [autoReconnect, clearReconnectTimeout, scheduleReconnect]);

  // Keep connectRef in sync
  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  const disconnect = useCallback(() => {
    shouldReconnectRef.current = false;
    clearReconnectTimeout();

    if (wsRef.current) {
      // Send unsubscribe
      if (wsRef.current.readyState === WebSocket.OPEN) {
        const request: SubscribeRequest = { type: "unsubscribe" };
        wsRef.current.send(JSON.stringify(request));
      }
      wsRef.current.close();
      wsRef.current = null;
    }

    setStatus("disconnected");
    setSubscriptionId(null);
  }, [clearReconnectTimeout]);

  const updateFilters = useCallback(
    (newSessionIds?: string[], newEventTypes?: SessionEventType[]) => {
      if (newSessionIds !== undefined) {
        filtersRef.current.sessionIds = newSessionIds;
      }
      if (newEventTypes !== undefined) {
        filtersRef.current.eventTypes = newEventTypes;
      }

      // Send update if connected
      if (wsRef.current?.readyState === WebSocket.OPEN && subscriptionId) {
        const request: SubscribeRequest = {
          type: "update",
          session_ids:
            filtersRef.current.sessionIds.length > 0
              ? filtersRef.current.sessionIds
              : undefined,
          event_types:
            filtersRef.current.eventTypes.length > 0
              ? filtersRef.current.eventTypes
              : undefined,
        };
        wsRef.current.send(JSON.stringify(request));
      }
    },
    [subscriptionId],
  );

  const clearEvents = useCallback(() => {
    setEvents([]);
  }, []);

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect) {
      connect();
    }

    return () => {
      shouldReconnectRef.current = false;
      clearReconnectTimeout();
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [autoConnect, connect, clearReconnectTimeout]);

  return {
    events,
    status,
    error,
    subscriptionId,
    connect,
    disconnect,
    updateFilters,
    clearEvents,
  };
}
