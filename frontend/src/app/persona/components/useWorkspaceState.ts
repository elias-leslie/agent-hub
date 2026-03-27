"use client";

import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  startTransition,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useChatStream, type ChatMessage } from "@agent-hub/chat-ui";

import { useSessionEvents } from "@/hooks/use-session-events";
import { INTERNAL_HEADERS, fetchApi, getApiBaseUrl, getCompleteApiUrl } from "@/lib/api-config";
import { fetchSessionEvents } from "@/lib/api/sessions";
import {
  type PersonaStreamMatch,
  type PersonaPulseSummary,
  fetchPersonaStream,
  type PersonaStreamEntry,
} from "@/lib/api/persona-stream";
import type { TimelineEvent } from "@/types/events";
import { useNarrationTags } from "../hooks/useNarrationTags";
import { entryHasPulseTag, filterModeToPulseTag, type FilterMode } from "./pulse-helpers";
import {
  type FeedAnchor,
  type FeedChildRun,
  type FeedHeartbeat,
  type FeedItem,
  type ItemTimelineBlock,
  type LiveSessionPatch,
  type RoutineHeartbeatTimelineBlock,
  type SessionEventDetailsState,
  type TimelineBlock,
  type TimelineRow,
  EMPTY_PULSE,
  LIVE_REFRESH_MS,
  PAGE_SIZE,
  PROGRAMMATIC_SCROLL_GRACE_MS,
  PROJECT_ID,
} from "./workspace-types";
import { isChildRunItem, canAnchorChildRuns, buildLocalFeedMessages, buildRemoteFeedItems } from "./workspace-feed";
import { isNearBottom, formatDayLabel } from "./workspace-utils";
import { mergeEventPreviews, buildLivePreview, liveSummaryFromEvent, liveStatusFromEvent, isRoutineHeartbeatBlock } from "./workspace-live-events";
import { getPersonaDisplayName, getPersonaPossessive } from "../utils/displayName";
import type { TimeRange } from "./TimeRangeDropdown";

export interface WorkspaceStateOptions {
  agentSlug: string;
  personaName?: string;
  activeSessionId: string | null;
  sidebarRefreshTrigger: number;
  runtimeSyncKey: string;
  onSelectSession: (sessionId: string | null) => void;
  onSessionCreated: (sessionId: string) => void;
  onNewSession: () => void;
}

export function useWorkspaceState({
  agentSlug,
  personaName,
  activeSessionId,
  sidebarRefreshTrigger,
  runtimeSyncKey,
  onSelectSession,
  onSessionCreated,
}: WorkspaceStateOptions) {
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [search, setSearch] = useState("");
  const [filterMode, setFilterMode] = useState<FilterMode>("all");
  const [showFilters, setShowFilters] = useState(false);
  const { narrationCache, fetchNarrationTags } = useNarrationTags();
  const [autoFollow, setAutoFollow] = useState(true);
  const deferredSearch = useDeferredValue(search);
  const [entries, setEntries] = useState<PersonaStreamEntry[]>([]);
  const [pulse, setPulse] = useState<PersonaPulseSummary>(EMPTY_PULSE);
  const [searchMatches, setSearchMatches] = useState<PersonaStreamMatch[]>([]);
  const [matchCount, setMatchCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [focusSessionId, setFocusSessionId] = useState<string | null>(null);
  const [anchorEntryId, setAnchorEntryId] = useState<string | null>(null);
  const [expandedEntryIds, setExpandedEntryIds] = useState<Record<string, boolean>>({});
  const [expandedRoutineGroupIds, setExpandedRoutineGroupIds] = useState<Record<string, boolean>>({});
  const [activeSearchMatchId, setActiveSearchMatchId] = useState<string | null>(null);
  const [liveRefreshTick, setLiveRefreshTick] = useState(0);
  const [liveSessionPatches, setLiveSessionPatches] = useState<Record<string, LiveSessionPatch>>({});
  const [sessionEventDetails, setSessionEventDetails] = useState<Record<string, SessionEventDetailsState>>({});
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [firstUnreadItemId, setFirstUnreadItemId] = useState<string | null>(null);

  const personaDisplayName = getPersonaDisplayName(personaName);
  const personaPossessive = getPersonaPossessive(personaName);

  const scrollRef = useRef<HTMLDivElement>(null);
  const autoFollowRef = useRef(true);
  const initialViewportTimeoutRef = useRef<number | null>(null);
  const programmaticScrollUntilRef = useRef(0);
  const initialViewportSettledRef = useRef(false);
  const lastReadItemIdRef = useRef<string | null>(null);
  const olderHistoryAnchorRef = useRef<{ scrollHeight: number; scrollTop: number } | null>(null);
  const sessionEventDetailsRef = useRef<Record<string, SessionEventDetailsState>>({});

  const apiConfig = useMemo(
    () => ({
      fetchHeaders: INTERNAL_HEADERS,
      completeEndpoint: getCompleteApiUrl(),
      sessionsEndpoint: `${getApiBaseUrl()}/api/sessions`,
      preferencesEndpoint: "/api/preferences",
      fetchFn: fetchApi,
      projectId: PROJECT_ID,
      memoryGroupPrefix: "agent:",
    }),
    [],
  );

  const {
    messages,
    status,
    error: chatError,
    currentSessionId,
    sendMessage,
    cancelStream,
  } = useChatStream({
    agentSlug,
    sessionId: activeSessionId || undefined,
    toolsEnabled: true,
    apiConfig,
    loadInitialSession: Boolean(activeSessionId),
  });

  const responseStatusLabel =
    status === "streaming"
      ? `${personaDisplayName} is responding`
      : status === "reconnecting"
        ? `Reconnecting to ${personaDisplayName}`
        : status === "cancelling"
          ? `Stopping ${personaDisplayName}'s response`
          : null;

  useEffect(() => {
    autoFollowRef.current = autoFollow;
  }, [autoFollow]);

  const scrollToBottom = (behavior: ScrollBehavior = "smooth") => {
    const container = scrollRef.current;
    if (!container || typeof container.scrollTo !== "function") return;
    programmaticScrollUntilRef.current = Date.now() + PROGRAMMATIC_SCROLL_GRACE_MS;
    container.scrollTo({ top: container.scrollHeight, behavior });
  };

  const clearInitialViewportTimeout = useCallback(() => {
    if (initialViewportTimeoutRef.current != null) {
      window.clearTimeout(initialViewportTimeoutRef.current);
      initialViewportTimeoutRef.current = null;
    }
  }, []);

  useEffect(() => {
    sessionEventDetailsRef.current = sessionEventDetails;
  }, [sessionEventDetails]);

  const loadSessionEventDetails = useCallback(async (sessionId: string, force = false) => {
    const existing = sessionEventDetailsRef.current[sessionId];
    if (!force) {
      if (existing?.loading) return;
      if (existing && existing.events.length > 0 && !existing.error) return;
    }

    setSessionEventDetails((current) => ({
      ...current,
      [sessionId]: {
        loading: true,
        error: null,
        events: current[sessionId]?.events ?? [],
      },
    }));

    try {
      const allEvents: TimelineEvent[] = [];
      let pageNumber = 1;
      let totalEvents = 0;
      do {
        const response = await fetchSessionEvents(sessionId, { page: pageNumber, page_size: 500 });
        totalEvents = response.total;
        allEvents.push(...response.events);
        pageNumber += 1;
      } while (allEvents.length < totalEvents);

      allEvents.sort((left, right) => {
        const turnDiff = left.turn - right.turn;
        if (turnDiff !== 0) return turnDiff;
        const seqDiff = left.sequence - right.sequence;
        if (seqDiff !== 0) return seqDiff;
        return +new Date(left.created_at) - +new Date(right.created_at);
      });

      setSessionEventDetails((current) => ({
        ...current,
        [sessionId]: { loading: false, error: null, events: allEvents },
      }));
    } catch (err) {
      setSessionEventDetails((current) => ({
        ...current,
        [sessionId]: {
          loading: false,
          error: err instanceof Error ? err.message : "Failed to load full session detail",
          events: current[sessionId]?.events ?? [],
        },
      }));
    }
  }, []);

  const hydratedEntries = useMemo(
    () =>
      entries.map((entry) => {
        const patch = liveSessionPatches[entry.session_id];
        if (!patch) return entry;
        return {
          ...entry,
          live_summary: patch.liveSummary ?? entry.live_summary,
          live_status: patch.liveStatus ?? entry.live_status,
          status:
            patch.liveStatus === "failed"
              ? "failed"
              : patch.liveStatus === "completed" && entry.status === "active"
                ? "completed"
                : entry.status,
          event_previews: mergeEventPreviews(entry.event_previews, patch.eventPreviews),
        };
      }),
    [entries, liveSessionPatches],
  );

  const mergedItems = useMemo(() => {
    const remote = buildRemoteFeedItems([...hydratedEntries].reverse(), personaDisplayName);
    const local = buildLocalFeedMessages(messages, currentSessionId || activeSessionId, personaDisplayName);
    return [...remote, ...local]
      .filter((item) => {
        if (filterMode === "all") return true;
        if (filterMode === "messages") return item.kind === "message";
        if (filterMode === "heartbeats") return item.kind === "heartbeat";
        if (filterMode === "work") return item.kind === "child_run" || item.kind === "heartbeat";
        const pulseTag = filterModeToPulseTag(filterMode);
        if (pulseTag) {
          if (item.kind === "message") {
            return pulseTag === "error" ? /error|failed|warning|blocked/i.test(item.message.content) : false;
          }
          return entryHasPulseTag(item.entry, pulseTag);
        }
        return true;
      })
      .sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
  }, [hydratedEntries, messages, currentSessionId, activeSessionId, filterMode]);

  const selectedSessionId = focusSessionId ?? activeSessionId;
  const latestItemId = mergedItems.at(-1)?.id ?? null;

  function markLatestAsRead(itemId: string | null = latestItemId) {
    if (!itemId) return;
    lastReadItemIdRef.current = itemId;
    setFirstUnreadItemId(null);
  }

  const activeStreamSessionIds = useMemo(() => {
    const activeIds = new Set<string>();
    for (const entry of hydratedEntries) {
      if (entry.status === "active" || entry.live_status === "active") {
        activeIds.add(entry.session_id);
      }
    }
    return Array.from(activeIds);
  }, [hydratedEntries]);

  const { status: liveEventsStatus } = useSessionEvents({
    sessionIds: activeStreamSessionIds,
    autoConnect: true,
    autoReconnect: true,
    onEvent: (event) => {
      const preview = buildLivePreview(event);
      const liveSummary = liveSummaryFromEvent(event);
      const liveStatus = liveStatusFromEvent(event);
      setLiveSessionPatches((current) => {
        const existing = current[event.session_id] ?? {
          liveSummary: null,
          liveStatus: null,
          eventPreviews: [],
        };
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
        window.setTimeout(() => {
          setLiveRefreshTick((value) => value + 1);
        }, 600);
      }
    },
  });

  useEffect(() => {
    if (!runtimeSyncKey) return;
    const expandedActiveSessionIds = Array.from(
      new Set(
        mergedItems
          .filter((item): item is FeedHeartbeat | FeedChildRun => item.kind !== "message")
          .filter((item) => expandedEntryIds[item.id] && activeStreamSessionIds.includes(item.sessionId))
          .map((item) => item.sessionId),
      ),
    );
    expandedActiveSessionIds.forEach((sessionId) => {
      void loadSessionEventDetails(sessionId, true);
    });
  }, [runtimeSyncKey, mergedItems, expandedEntryIds, activeStreamSessionIds, loadSessionEventDetails]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    const handleScroll = () => {
      const nearBottom = isNearBottom(container);
      setIsAtBottom(nearBottom);
      if (Date.now() < programmaticScrollUntilRef.current) return;
      if (nearBottom) {
        if (!autoFollowRef.current) setAutoFollow(true);
        if (latestItemId) {
          lastReadItemIdRef.current = latestItemId;
          setFirstUnreadItemId(null);
        }
        return;
      }
      if (autoFollowRef.current && !nearBottom) {
        clearInitialViewportTimeout();
        setAutoFollow(false);
      }
    };
    container.addEventListener("scroll", handleScroll, { passive: true });
    return () => container.removeEventListener("scroll", handleScroll);
  }, [clearInitialViewportTimeout, latestItemId]);

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
    let cancelled = false;
    setLoading(true);
    const effectiveRange = deferredSearch.trim() ? "all" : timeRange;
    fetchPersonaStream({
      timeRange: effectiveRange,
      search: deferredSearch.trim() || undefined,
      focusSessionId,
      anchorEntryId,
      page,
      pageSize: PAGE_SIZE,
    })
      .then((data) => {
        if (cancelled) return;
        startTransition(() => {
          setEntries((prev) => {
            if (page === 1) return data.entries;
            const merged = [...prev];
            for (const entry of data.entries) {
              if (!merged.some((existing) => existing.id === entry.id)) {
                merged.push(entry);
              }
            }
            return merged;
          });
          setTotal(data.total);
          setSearchMatches(data.matches);
          setMatchCount(data.match_count);
          setPulse(data.pulse ?? EMPTY_PULSE);
          setError(null);
          setLoading(false);
        });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load stream");
          setPulse(EMPTY_PULSE);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [timeRange, deferredSearch, focusSessionId, anchorEntryId, page, currentSessionId, sidebarRefreshTrigger, liveRefreshTick, runtimeSyncKey]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container || !autoFollow) return;
    scrollToBottom("smooth");
    setIsAtBottom(true);
    markLatestAsRead();
  }, [messages.length, status, autoFollow]);

  useEffect(() => {
    if (initialViewportSettledRef.current || loading || !autoFollow) return;
    if (deferredSearch.trim() || focusSessionId || anchorEntryId) return;
    if (hydratedEntries.length === 0 && messages.length === 0) return;
    initialViewportSettledRef.current = true;
    clearInitialViewportTimeout();
    initialViewportTimeoutRef.current = window.setTimeout(() => {
      requestAnimationFrame(() => {
        scrollToBottom("auto");
        setIsAtBottom(true);
        markLatestAsRead();
        initialViewportTimeoutRef.current = null;
      });
    }, 0);
    return () => clearInitialViewportTimeout();
  }, [anchorEntryId, autoFollow, clearInitialViewportTimeout, deferredSearch, focusSessionId, hydratedEntries.length, loading, messages.length]);

  useEffect(() => {
    if (!latestItemId) return;
    if (!lastReadItemIdRef.current) {
      lastReadItemIdRef.current = latestItemId;
      return;
    }
    if (latestItemId === lastReadItemIdRef.current) return;
    if (autoFollow && isAtBottom) {
      markLatestAsRead(latestItemId);
      return;
    }
    const previousIndex = mergedItems.findIndex((item) => item.id === lastReadItemIdRef.current);
    const nextUnreadId = mergedItems[Math.max(previousIndex + 1, 0)]?.id ?? latestItemId;
    setFirstUnreadItemId((current) => current ?? nextUnreadId);
  }, [latestItemId, mergedItems, autoFollow, isAtBottom]);

  useEffect(() => {
    if (!autoFollow) return;
    const hasLiveWork = hydratedEntries.some((entry) => entry.status === "active" || entry.live_status === "active");
    if (!hasLiveWork) return;
    const container = scrollRef.current;
    if (!container || !isNearBottom(container)) return;
    scrollToBottom("smooth");
    setIsAtBottom(true);
    markLatestAsRead();
  }, [autoFollow, hydratedEntries]);

  useEffect(() => {
    const container = scrollRef.current;
    const anchor = olderHistoryAnchorRef.current;
    if (!container || !anchor || loading) return;
    const heightDelta = container.scrollHeight - anchor.scrollHeight;
    container.scrollTop = anchor.scrollTop + Math.max(heightDelta, 0);
    olderHistoryAnchorRef.current = null;
  }, [entries, loading]);

  useEffect(() => {
    const hasLiveWork = hydratedEntries.some((entry) => entry.status === "active" || entry.live_status === "active");
    if (!hasLiveWork || liveEventsStatus === "connected") return;
    const interval = window.setInterval(() => {
      setLiveRefreshTick((value) => value + 1);
    }, LIVE_REFRESH_MS);
    return () => window.clearInterval(interval);
  }, [hydratedEntries, liveEventsStatus]);

  const groupedItems = useMemo(() => {
    const groups: Array<{ label: string; blocks: TimelineBlock[] }> = [];
    let currentLabel = "";
    for (const item of mergedItems) {
      const label = formatDayLabel(item.timestamp);
      if (label !== currentLabel) {
        currentLabel = label;
        groups.push({ label, blocks: [] });
      }
      const currentBlocks = groups[groups.length - 1].blocks;
      if (isChildRunItem(item) && item.entry.parent_session_id) {
        const parentBlockIndex = currentBlocks.findLastIndex(
          (block) =>
            block.kind === "item" &&
            canAnchorChildRuns(block.anchorItem) &&
            block.anchorItem.sessionId === item.entry.parent_session_id,
        );
        if (parentBlockIndex >= 0) {
          const parentBlock = currentBlocks[parentBlockIndex];
          if (parentBlock.kind === "item") {
            parentBlock.childRuns.push(item);
          }
          continue;
        }
      }
      currentBlocks.push({ kind: "item", anchorItem: item, childRuns: [] });
    }
    return groups.map((group) => {
      const compressedBlocks: TimelineBlock[] = [];
      let pendingRoutine: ItemTimelineBlock[] = [];
      const flushRoutine = () => {
        if (pendingRoutine.length === 0) return;
        if (pendingRoutine.length === 1) {
          compressedBlocks.push(pendingRoutine[0]);
        } else {
          compressedBlocks.push({
            kind: "routine_group",
            id: `routine:${pendingRoutine[0].anchorItem.id}:${pendingRoutine.at(-1)?.anchorItem.id}`,
            items: pendingRoutine.map((block) => ({
              anchorItem: block.anchorItem as FeedHeartbeat,
              childRuns: block.childRuns,
            })),
          });
        }
        pendingRoutine = [];
      };
      for (const block of group.blocks) {
        if (block.kind !== "item") {
          flushRoutine();
          compressedBlocks.push(block);
          continue;
        }
        if (isRoutineHeartbeatBlock(block, !!deferredSearch.trim(), filterMode)) {
          pendingRoutine.push(block);
          continue;
        }
        flushRoutine();
        compressedBlocks.push(block);
      }
      flushRoutine();
      return { ...group, blocks: compressedBlocks };
    });
  }, [mergedItems, deferredSearch, filterMode]);

  const timelineRows = useMemo(() => {
    const rows: TimelineRow[] = [];
    for (const group of groupedItems) {
      rows.push({ kind: "divider", id: `divider:${group.label}`, label: group.label });
      for (const block of group.blocks) {
        if (block.kind === "routine_group") {
          const containsUnread = Boolean(
            firstUnreadItemId &&
              block.items.some(
                ({ anchorItem, childRuns }) =>
                  anchorItem.id === firstUnreadItemId || childRuns.some((cr) => cr.id === firstUnreadItemId),
              ),
          );
          if (containsUnread) {
            rows.push({ kind: "unread", id: `unread:${block.id}` });
          }
          rows.push({ kind: "routine_group", id: block.id, block });
          continue;
        }
        if (
          firstUnreadItemId &&
          (block.anchorItem.id === firstUnreadItemId || block.childRuns.some((cr) => cr.id === firstUnreadItemId))
        ) {
          rows.push({ kind: "unread", id: `unread:${block.anchorItem.id}` });
        }
        rows.push({
          kind: "item",
          id: `item:${block.anchorItem.id}`,
          item: block.anchorItem,
          childRuns: block.childRuns,
        });
      }
    }
    return rows;
  }, [groupedItems, firstUnreadItemId]);

  const rowIndexByStreamItemId = useMemo(() => {
    const indexMap = new Map<string, number>();
    timelineRows.forEach((row, index) => {
      if (row.kind === "item") {
        indexMap.set(row.item.id, index);
        row.childRuns.forEach((cr) => indexMap.set(cr.id, index));
        return;
      }
      if (row.kind === "routine_group") {
        row.block.items.forEach(({ anchorItem, childRuns }) => {
          indexMap.set(anchorItem.id, index);
          childRuns.forEach((cr) => indexMap.set(cr.id, index));
        });
      }
    });
    return indexMap;
  }, [timelineRows]);

  const rowIndexBySessionId = useMemo(() => {
    const indexMap = new Map<string, number>();
    timelineRows.forEach((row, index) => {
      if (row.kind === "item") {
        if (row.item.sessionId) indexMap.set(row.item.sessionId, index);
        row.childRuns.forEach((cr) => indexMap.set(cr.sessionId, index));
        return;
      }
      if (row.kind === "routine_group") {
        row.block.items.forEach(({ anchorItem, childRuns }) => {
          indexMap.set(anchorItem.sessionId, index);
          childRuns.forEach((cr) => indexMap.set(cr.sessionId, index));
        });
      }
    });
    return indexMap;
  }, [timelineRows]);

  const filterCounts = useMemo(() => {
    const counts: Record<FilterMode, number> = {
      all: hydratedEntries.length + messages.length,
      messages: [...hydratedEntries.filter((e) => e.entry_type === "message"), ...messages].length,
      work: hydratedEntries.filter((e) => e.entry_type === "heartbeat" || e.entry_type === "child_run").length,
      heartbeats: hydratedEntries.filter((e) => e.entry_type === "heartbeat").length,
      friction: hydratedEntries.filter((e) => entryHasPulseTag(e, "friction")).length,
      errors: hydratedEntries.filter((e) => entryHasPulseTag(e, "error")).length,
      warnings: hydratedEntries.filter((e) => entryHasPulseTag(e, "warning")).length,
      stalled: hydratedEntries.filter((e) => entryHasPulseTag(e, "stalled")).length,
      drift: hydratedEntries.filter((e) => entryHasPulseTag(e, "instruction_drift")).length,
      tool_friction: hydratedEntries.filter((e) => entryHasPulseTag(e, "tool_friction")).length,
      retries: hydratedEntries.filter((e) => entryHasPulseTag(e, "retries")).length,
      recovered: hydratedEntries.filter((e) => entryHasPulseTag(e, "recovered")).length,
      escalations: hydratedEntries.filter((e) => entryHasPulseTag(e, "escalation")).length,
    };
    return counts;
  }, [hydratedEntries, messages]);

  const newActivityCount = useMemo(() => {
    if (!firstUnreadItemId) return 0;
    const unreadIndex = mergedItems.findIndex((item) => item.id === firstUnreadItemId);
    if (unreadIndex < 0) return 0;
    return mergedItems.length - unreadIndex;
  }, [firstUnreadItemId, mergedItems]);

  const matchedIds = useMemo(() => new Set(searchMatches.map((item) => item.entry_id)), [searchMatches]);
  const activeSearchMatch = useMemo(
    () => searchMatches.findIndex((item) => item.entry_id === activeSearchMatchId),
    [activeSearchMatchId, searchMatches],
  );
  const activeMatchId = !deferredSearch.trim()
    ? null
    : activeSearchMatchId && searchMatches.some((item) => item.entry_id === activeSearchMatchId)
      ? activeSearchMatchId
      : searchMatches[0]?.entry_id ?? null;

  useEffect(() => {
    if (!deferredSearch.trim()) {
      setActiveSearchMatchId(null);
      return;
    }
    if (searchMatches.length === 0) return;
    if (!activeSearchMatchId || !searchMatches.some((item) => item.entry_id === activeSearchMatchId)) {
      setActiveSearchMatchId(searchMatches[0]?.entry_id ?? null);
    }
  }, [deferredSearch, searchMatches, activeSearchMatchId]);

  const virtualizer = useVirtualizer({
    count: timelineRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) => {
      const row = timelineRows[index];
      if (!row) return 80;
      if (row.kind === "divider") return 56;
      if (row.kind === "unread") return 40;
      if (row.kind === "routine_group") return expandedRoutineGroupIds[row.block.id] ? 360 : 120;
      const expanded = row.item.kind !== "message" && expandedEntryIds[row.item.id];
      const childRunCount = row.childRuns.length;
      return expanded ? 420 + childRunCount * 140 : 160 + childRunCount * 140;
    },
    overscan: 10,
  });

  useEffect(() => {
    if (!activeMatchId) return;
    if (hydratedEntries.some((entry) => entry.id === activeMatchId && entry.entry_type !== "message")) {
      setExpandedEntryIds((current) =>
        current[activeMatchId] ? current : { ...current, [activeMatchId]: true },
      );
    }
    const loaded = mergedItems.some((item) => item.id === activeMatchId);
    if (!loaded && anchorEntryId !== activeMatchId) {
      setAnchorEntryId(activeMatchId);
      return;
    }
    const rowIndex = rowIndexByStreamItemId.get(activeMatchId);
    if (rowIndex != null) virtualizer.scrollToIndex(rowIndex, { align: "center" });
    const timeout = window.setTimeout(() => {
      const node = document.querySelector<HTMLElement>(`[data-stream-item-id="${activeMatchId}"]`);
      node?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timeout);
  }, [activeMatchId, mergedItems, anchorEntryId, rowIndexByStreamItemId, virtualizer]);

  useEffect(() => {
    if (!focusSessionId) return;
    const rowIndex = rowIndexBySessionId.get(focusSessionId);
    if (rowIndex != null) virtualizer.scrollToIndex(rowIndex, { align: "center" });
    const timeout = window.setTimeout(() => {
      const nodes = document.querySelectorAll<HTMLElement>(`[data-session-anchor="${focusSessionId}"]`);
      const target = nodes.length > 0 ? nodes[nodes.length - 1] : null;
      target?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timeout);
  }, [entries, focusSessionId, rowIndexBySessionId, virtualizer]);

  const visibleSearchMatches = useMemo(() => {
    if (searchMatches.length === 0) return [];
    if (activeSearchMatch < 0) return searchMatches.slice(0, 5);
    const start = Math.max(activeSearchMatch - 2, 0);
    const end = Math.min(start + 5, searchMatches.length);
    return searchMatches.slice(Math.max(end - 5, 0), end);
  }, [searchMatches, activeSearchMatch]);

  const visiblePulseMetrics = useMemo(
    () => pulse.metrics.filter((metric) => metric.count > 0 || metric.key === "friction"),
    [pulse.metrics],
  );

  const hasExpandedTimelineContent = useMemo(
    () => Object.values(expandedEntryIds).some(Boolean) || Object.values(expandedRoutineGroupIds).some(Boolean),
    [expandedEntryIds, expandedRoutineGroupIds],
  );

  // --- handlers ---

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

  const toggleRoutineGroup = (groupId: string) => {
    setExpandedRoutineGroupIds((current) => ({ ...current, [groupId]: !current[groupId] }));
  };

  const jumpToSearchMatch = (direction: 1 | -1) => {
    if (searchMatches.length === 0) return;
    const currentIndex = searchMatches.findIndex((item) => item.entry_id === activeMatchId);
    const resolvedIndex = currentIndex >= 0 ? currentIndex : 0;
    const nextIndex = resolvedIndex + direction;
    if (nextIndex < 0) {
      setActiveSearchMatchId(searchMatches.at(-1)?.entry_id ?? null);
      setAnchorEntryId(searchMatches.at(-1)?.entry_id ?? null);
      setAutoFollow(false);
      return;
    }
    if (nextIndex >= searchMatches.length) {
      setActiveSearchMatchId(searchMatches[0]?.entry_id ?? null);
      setAnchorEntryId(searchMatches[0]?.entry_id ?? null);
      setAutoFollow(false);
      return;
    }
    setActiveSearchMatchId(searchMatches[nextIndex].entry_id);
    setAnchorEntryId(searchMatches[nextIndex].entry_id);
    setAutoFollow(false);
  };

  const applyPulseFilter = (nextMode: FilterMode, nextAnchorEntryId?: string | null) => {
    setFilterMode(nextMode);
    if (nextAnchorEntryId) {
      setAnchorEntryId(nextAnchorEntryId);
      setExpandedEntryIds((current) => ({ ...current, [nextAnchorEntryId]: true }));
      setAutoFollow(false);
    }
  };

  const inspectAgentPulse = (agentSlugValue: string) => {
    setFilterMode("friction");
    setSearch(`agent:${agentSlugValue}`);
    setAnchorEntryId(null);
    setAutoFollow(false);
  };

  const handleLoadOlder = () => {
    const container = scrollRef.current;
    if (container) {
      olderHistoryAnchorRef.current = {
        scrollHeight: container.scrollHeight,
        scrollTop: container.scrollTop,
      };
    }
    setPage((value) => value + 1);
  };

  const handleJumpToLatest = () => {
    setAutoFollow(true);
    scrollToBottom("smooth");
    setIsAtBottom(true);
    markLatestAsRead();
  };

  return {
    // display
    personaDisplayName,
    personaPossessive,
    // search/filter state
    search,
    setSearch,
    setAnchorEntryId,
    filterMode,
    setFilterMode,
    showFilters,
    setShowFilters,
    deferredSearch,
    filterCounts,
    timeRange,
    setTimeRange,
    // search results
    matchCount,
    activeSearchMatch,
    activeMatchId,
    matchedIds,
    visibleSearchMatches,
    jumpToSearchMatch,
    // data
    entries,
    pulse,
    visiblePulseMetrics,
    loading,
    error,
    total,
    // processed data
    hydratedEntries,
    mergedItems,
    groupedItems,
    timelineRows,
    // session
    selectedSessionId,
    sessionEventDetails,
    narrationCache,
    fetchNarrationTags,
    // scroll/viewport
    scrollRef,
    autoFollow,
    isAtBottom,
    newActivityCount,
    latestItemId,
    // expand state
    expandedEntryIds,
    expandedRoutineGroupIds,
    hasExpandedTimelineContent,
    // virtualizer
    virtualizer,
    // chat
    messages,
    status,
    chatError,
    currentSessionId,
    sendMessage,
    cancelStream,
    responseStatusLabel,
    apiConfig,
    // pulse
    activeIssueTag: filterMode === "friction" ? ("friction" as const) : filterModeToPulseTag(filterMode),
    // handlers
    handleSessionJump,
    toggleExpanded,
    toggleRoutineGroup,
    applyPulseFilter,
    inspectAgentPulse,
    handleLoadOlder,
    handleJumpToLatest,
    markLatestAsRead,
  };
}
