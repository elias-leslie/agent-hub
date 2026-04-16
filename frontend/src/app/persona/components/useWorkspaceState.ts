"use client";

import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { useSessionEvents } from "@/hooks/use-session-events";
import type { FeedItem, LiveSessionPatch } from "./workspace-types";
import { LIVE_REFRESH_MS } from "./workspace-types";
import { type FilterMode, filterModeToPulseTag } from "./pulse-helpers";
import { buildLivePreview, liveSummaryFromEvent, liveStatusFromEvent, mergeEventPreviews } from "./workspace-live-events";
import { getPersonaDisplayName, getPersonaPossessive } from "../utils/displayName";
import { useNarrationTags } from "../hooks/useNarrationTags";
import type { TimeRange } from "./TimeRangeDropdown";
import { useWorkspaceChatStream } from "./useWorkspaceChatStream";
import { useSessionEventDetails } from "./useSessionEventDetails";
import { usePersonaFeed } from "./usePersonaFeed";
import { useWorkspaceTimeline } from "./useWorkspaceTimeline";
import { useWorkspaceScroll } from "./useWorkspaceScroll";
import { useWorkspaceSearch } from "./useWorkspaceSearch";
import { useWorkspaceViewport } from "./useWorkspaceViewport";

export interface WorkspaceStateOptions {
  agentSlug: string;
  personaName?: string;
  activeSessionId: string | null;
  targetProjectId: string;
  sessionProjectId: string | null;
  sidebarRefreshTrigger: number;
  runtimeSyncKey: string;
  onSelectSession: (sessionId: string | null) => void;
  onSessionCreated: (sessionId: string) => void;
  onNewSession: () => void;
}

function getExpandedActiveSessionIds(
  mergedItems: FeedItem[],
  expandedEntryIds: Record<string, boolean>,
  activeStreamSessionIds: string[],
): string[] {
  return Array.from(
    new Set(
      mergedItems
        .filter((item): item is Extract<FeedItem, { kind: "heartbeat" | "child_run" }> => item.kind !== "message")
        .filter((item) => expandedEntryIds[item.id] && activeStreamSessionIds.includes(item.sessionId))
        .map((item) => item.sessionId),
    ),
  );
}

export function useWorkspaceState({
  agentSlug,
  personaName,
  activeSessionId,
  targetProjectId,
  sessionProjectId,
  sidebarRefreshTrigger,
  runtimeSyncKey,
  onSelectSession,
  onSessionCreated,
}: WorkspaceStateOptions) {
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [search, setSearch] = useState("");
  const [filterMode, setFilterMode] = useState<FilterMode>("all");
  const [showFilters, setShowFilters] = useState(false);
  const [page, setPage] = useState(1);
  const [focusSessionId, setFocusSessionId] = useState<string | null>(null);
  const [anchorEntryId, setAnchorEntryId] = useState<string | null>(null);
  const [expandedEntryIds, setExpandedEntryIds] = useState<Record<string, boolean>>({});
  const [expandedRoutineGroupIds, setExpandedRoutineGroupIds] = useState<Record<string, boolean>>({});
  const [liveRefreshTick, setLiveRefreshTick] = useState(0);
  const [liveSessionPatches, setLiveSessionPatches] = useState<Record<string, LiveSessionPatch>>({});

  const personaDisplayName = getPersonaDisplayName(personaName);
  const personaPossessive = getPersonaPossessive(personaName);
  const deferredSearch = useDeferredValue(search);
  const { narrationCache, fetchNarrationTags } = useNarrationTags();
  const chatProjectId = sessionProjectId ?? targetProjectId;

  const {
    apiConfig,
    messages,
    status,
    chatError,
    currentSessionId,
    sendMessage,
    cancelStream,
    resetSession,
    responseStatusLabel,
  } =
    useWorkspaceChatStream({ agentSlug, personaDisplayName, activeSessionId, projectId: chatProjectId });

  const { sessionEventDetails, loadSessionEventDetails } = useSessionEventDetails();

  const { entries, pulse, visiblePulseMetrics, searchMatches, matchCount, loading, error, total, hydratedEntries, mergedItems, activeStreamSessionIds } =
    usePersonaFeed({
      timeRange, deferredSearch, focusSessionId, anchorEntryId, page,
      currentSessionId, activeSessionId, sidebarRefreshTrigger, liveRefreshTick,
      runtimeSyncKey, filterMode, liveSessionPatches, messages, personaDisplayName,
    });

  const latestItemId = mergedItems.at(-1)?.id ?? null;

  const {
    scrollRef, autoFollow, setAutoFollow, isAtBottom, setIsAtBottom,
    firstUnreadItemId, setFirstUnreadItemId, lastReadItemIdRef, initialViewportSettledRef,
    scrollToBottom, clearInitialViewportTimeout, markLatestAsRead, captureScrollAnchor,
  } = useWorkspaceScroll({ latestItemId, loading });

  const { groupedItems, timelineRows, rowIndexByStreamItemId, rowIndexBySessionId, virtualizer, hasExpandedTimelineContent } =
    useWorkspaceTimeline({ mergedItems, deferredSearch, filterMode, firstUnreadItemId, expandedEntryIds, expandedRoutineGroupIds, scrollRef });

  const { activeSearchMatchId, setActiveSearchMatchId, activeSearchMatch, activeMatchId, matchedIds, visibleSearchMatches, filterCounts } =
    useWorkspaceSearch({ deferredSearch, searchMatches, matchCount, hydratedEntries, messages, filterMode });

  // Live events — must be declared before effects that reference liveEventsStatus
  const { status: liveEventsStatus } = useSessionEvents({
    sessionIds: activeStreamSessionIds,
    autoConnect: true,
    autoReconnect: true,
    onEvent: (event) => {
      const preview = buildLivePreview(event);
      const liveSummary = liveSummaryFromEvent(event);
      const liveStatus = liveStatusFromEvent(event);
      setLiveSessionPatches((current) => {
        const existing = current[event.session_id] ?? { liveSummary: null, liveStatus: null, eventPreviews: [] };
        return {
          ...current,
          [event.session_id]: {
            liveSummary: liveSummary ?? existing.liveSummary,
            liveStatus: liveStatus ?? existing.liveStatus,
            eventPreviews: preview ? mergeEventPreviews(existing.eventPreviews, [preview]) : existing.eventPreviews,
          },
        };
      });
      if (!entries.some((entry) => entry.session_id === event.session_id)) {
        setLiveRefreshTick((value) => value + 1);
        return;
      }
      if (event.event_type === "complete" || event.event_type === "error") {
        window.setTimeout(() => setLiveRefreshTick((value) => value + 1), 600);
      }
    },
  });

  useWorkspaceViewport({
    autoFollow, isAtBottom, loading, deferredSearch, focusSessionId, anchorEntryId,
    latestItemId, mergedItems, hydratedEntries, messagesLength: messages.length, status,
    scrollRef, lastReadItemIdRef, initialViewportSettledRef,
    scrollToBottom, clearInitialViewportTimeout, markLatestAsRead, setIsAtBottom, setFirstUnreadItemId,
  });

  const selectedSessionId = focusSessionId ?? activeSessionId;

  // --- Coordination effects ---

  useEffect(() => {
    if (currentSessionId) onSessionCreated(currentSessionId);
  }, [currentSessionId, onSessionCreated]);

  useEffect(() => {
    if (!deferredSearch.trim()) setAnchorEntryId(null);
    setPage(1);
  }, [timeRange, deferredSearch, focusSessionId, currentSessionId]);

  useEffect(() => {
    initialViewportSettledRef.current = false;
    clearInitialViewportTimeout();
  }, [timeRange, deferredSearch, focusSessionId, anchorEntryId, activeSessionId, clearInitialViewportTimeout]);

  useEffect(() => {
    if (!runtimeSyncKey) return;
    const ids = getExpandedActiveSessionIds(mergedItems, expandedEntryIds, activeStreamSessionIds);
    ids.forEach((sessionId) => void loadSessionEventDetails(sessionId, true));
  }, [runtimeSyncKey, mergedItems, expandedEntryIds, activeStreamSessionIds, loadSessionEventDetails]);

  useEffect(() => {
    const hasLiveWork = hydratedEntries.some((entry) => entry.status === "active" || entry.live_status === "active");
    if (!hasLiveWork || liveEventsStatus === "connected") return;
    const interval = window.setInterval(() => setLiveRefreshTick((v) => v + 1), LIVE_REFRESH_MS);
    return () => window.clearInterval(interval);
  }, [hydratedEntries, liveEventsStatus]);

  useEffect(() => {
    if (!activeMatchId) return;
    if (hydratedEntries.some((entry) => entry.id === activeMatchId && entry.entry_type !== "message")) {
      setExpandedEntryIds((current) => current[activeMatchId] ? current : { ...current, [activeMatchId]: true });
    }
    const loaded = mergedItems.some((item) => item.id === activeMatchId);
    if (!loaded && anchorEntryId !== activeMatchId) {
      setAnchorEntryId(activeMatchId);
      return;
    }
    const rowIndex = rowIndexByStreamItemId.get(activeMatchId);
    if (rowIndex != null) virtualizer.scrollToIndex(rowIndex, { align: "center" });
    const timeout = window.setTimeout(() => {
      document.querySelector<HTMLElement>(`[data-stream-item-id="${activeMatchId}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timeout);
  }, [activeMatchId, mergedItems, anchorEntryId, rowIndexByStreamItemId, virtualizer]);

  useEffect(() => {
    if (!focusSessionId) return;
    const rowIndex = rowIndexBySessionId.get(focusSessionId);
    if (rowIndex != null) virtualizer.scrollToIndex(rowIndex, { align: "center" });
    const timeout = window.setTimeout(() => {
      const nodes = document.querySelectorAll<HTMLElement>(`[data-session-anchor="${focusSessionId}"]`);
      nodes[nodes.length - 1]?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timeout);
  }, [entries, focusSessionId, rowIndexBySessionId, virtualizer]);

  // --- Derived values ---

  const newActivityCount = useMemo(() => {
    if (!firstUnreadItemId) return 0;
    const unreadIndex = mergedItems.findIndex((item) => item.id === firstUnreadItemId);
    return unreadIndex < 0 ? 0 : mergedItems.length - unreadIndex;
  }, [firstUnreadItemId, mergedItems]);

  // --- Handlers ---

  const handleSessionJump = (sessionId: string | null) => {
    onSelectSession(sessionId);
    setFocusSessionId(sessionId);
    setAnchorEntryId(null);
    setAutoFollow(false);
  };

  const toggleExpanded = (entryId: string, sessionId?: string, externalId?: string) => {
    const willExpand = !expandedEntryIds[entryId];
    if (willExpand && sessionId) void loadSessionEventDetails(sessionId);
    if (willExpand && externalId) void fetchNarrationTags(externalId);
    setExpandedEntryIds((current) => ({ ...current, [entryId]: !current[entryId] }));
  };

  const toggleRoutineGroup = (groupId: string) =>
    setExpandedRoutineGroupIds((current) => ({ ...current, [groupId]: !current[groupId] }));

  const jumpToSearchMatch = (direction: 1 | -1) => {
    if (searchMatches.length === 0) return;
    const currentIndex = searchMatches.findIndex((item) => item.entry_id === activeMatchId);
    const resolvedIndex = currentIndex >= 0 ? currentIndex : 0;
    const nextIndex = resolvedIndex + direction;
    const wrappedEntry =
      nextIndex < 0 ? searchMatches.at(-1)?.entry_id
      : nextIndex >= searchMatches.length ? searchMatches[0]?.entry_id
      : searchMatches[nextIndex].entry_id;
    setActiveSearchMatchId(wrappedEntry ?? null);
    setAnchorEntryId(wrappedEntry ?? null);
    setAutoFollow(false);
  };

  const applyPulseFilter = (nextMode: FilterMode, nextAnchorEntryId?: string | null) => {
    setFilterMode(nextMode);
    if (!nextAnchorEntryId) return;
    setAnchorEntryId(nextAnchorEntryId);
    setExpandedEntryIds((current) => ({ ...current, [nextAnchorEntryId]: true }));
    setAutoFollow(false);
  };

  const inspectAgentPulse = (agentSlugValue: string) => {
    setFilterMode("friction");
    setSearch(`agent:${agentSlugValue}`);
    setAnchorEntryId(null);
    setAutoFollow(false);
  };

  const handleLoadOlder = () => {
    captureScrollAnchor();
    setPage((value) => value + 1);
  };

  const handleJumpToLatest = () => {
    setAutoFollow(true);
    scrollToBottom("smooth");
    setIsAtBottom(true);
    markLatestAsRead();
  };

  return {
    personaDisplayName, personaPossessive,
    search, setSearch, setAnchorEntryId, filterMode, setFilterMode,
    showFilters, setShowFilters, deferredSearch, filterCounts, timeRange, setTimeRange,
    matchCount, activeSearchMatch, activeMatchId, matchedIds, visibleSearchMatches, jumpToSearchMatch,
    entries, pulse, visiblePulseMetrics, loading, error, total,
    hydratedEntries, mergedItems, groupedItems, timelineRows,
    selectedSessionId, sessionEventDetails, narrationCache, fetchNarrationTags,
    scrollRef, autoFollow, isAtBottom, newActivityCount, latestItemId,
    expandedEntryIds, expandedRoutineGroupIds, hasExpandedTimelineContent,
    virtualizer,
    messages, status, chatError, currentSessionId, sendMessage, cancelStream, resetSession, responseStatusLabel, apiConfig,
    activeIssueTag: filterMode === "friction" ? ("friction" as const) : filterModeToPulseTag(filterMode),
    handleSessionJump, toggleExpanded, toggleRoutineGroup, applyPulseFilter,
    inspectAgentPulse, handleLoadOlder, handleJumpToLatest, markLatestAsRead,
  };
}
