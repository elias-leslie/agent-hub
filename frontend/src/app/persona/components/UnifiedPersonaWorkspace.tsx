"use client";

import {
  useCallback,
  useDeferredValue,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  startTransition,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  CircleDot,
  Filter,
  HeartPulse,
  Loader2,
  MessageSquarePlus,
  Search,
  X,
} from "lucide-react";
import {
  MessageBubble,
  MessageInput,
  useChatStream,
  type ChatMessage,
} from "@agent-hub/chat-ui";

import { useSessionEvents } from "@/hooks/use-session-events";
import { cn } from "@/lib/utils";
import { INTERNAL_HEADERS, fetchApi, getApiBaseUrl, getCompleteApiUrl, getWsUrl } from "@/lib/api-config";
import { fetchSessionEvents } from "@/lib/api/sessions";
import {
  type PersonaStreamMatch,
  type PersonaPulseSummary,
  fetchPersonaStream,
  type PersonaStreamEntry,
} from "@/lib/api/persona-stream";
import type { SessionEvent as LiveSessionEvent, TimelineEvent } from "@/types/events";
import { TimeRangeDropdown, type TimeRange } from "./TimeRangeDropdown";
import { useNarrationTags } from "../hooks/useNarrationTags";
import {
  entryHasPulseTag,
  filterModeToPulseTag,
  type FilterMode,
  pulseTagToFilterMode,
} from "./pulse-helpers";

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
import {
  DateDivider,
  HighlightedText,
  TimelineTimestamp,
  formatDayLabel,
  formatTimeLabel,
  isNearBottom,
  shortenText,
} from "./workspace-utils";
import { mergeEventPreviews, buildLivePreview, liveSummaryFromEvent, liveStatusFromEvent, isRoutineHeartbeatBlock } from "./workspace-live-events";
import {
  ChildRunCard,
  ChildRunStack,
  HeartbeatCard,
  PulseOverviewPanels,
  RoutineHeartbeatGroup,
} from "./workspace-cards";
import { getPersonaDisplayName, getPersonaPossessive } from "../utils/displayName";

interface UnifiedPersonaWorkspaceProps {
  agentSlug: string;
  personaName?: string;
  activeSessionId: string | null;
  sidebarRefreshTrigger: number;
  runtimeSyncKey: string;
  onSelectSession: (sessionId: string | null) => void;
  onSessionCreated: (sessionId: string) => void;
  onNewSession: () => void;
}

export function UnifiedPersonaWorkspace({
  agentSlug,
  personaName,
  activeSessionId,
  sidebarRefreshTrigger,
  runtimeSyncKey,
  onSelectSession,
  onSessionCreated,
  onNewSession,
}: UnifiedPersonaWorkspaceProps) {
  const searchInputId = useId();
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
    if (!container || typeof container.scrollTo !== "function") {
      return;
    }
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
      if (existing?.loading) {
        return;
      }
      if (existing && existing.events.length > 0 && !existing.error) {
        return;
      }
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
      let total = 0;
      do {
        const response = await fetchSessionEvents(sessionId, { page: pageNumber, page_size: 500 });
        total = response.total;
        allEvents.push(...response.events);
        pageNumber += 1;
      } while (allEvents.length < total);

      allEvents.sort((left, right) => {
        const turnDifference = left.turn - right.turn;
        if (turnDifference !== 0) {
          return turnDifference;
        }
        const sequenceDifference = left.sequence - right.sequence;
        if (sequenceDifference !== 0) {
          return sequenceDifference;
        }
        return +new Date(left.created_at) - +new Date(right.created_at);
      });

      setSessionEventDetails((current) => ({
        ...current,
        [sessionId]: {
          loading: false,
          error: null,
          events: allEvents,
        },
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
        if (!patch) {
          return entry;
        }
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
        if (filterMode === "work") {
          return item.kind === "child_run" || item.kind === "heartbeat";
        }
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
    if (!itemId) {
      return;
    }
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
    if (!runtimeSyncKey) {
      return;
    }
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
    if (!container) {
      return;
    }
    const handleScroll = () => {
      const nearBottom = isNearBottom(container);
      setIsAtBottom(nearBottom);
      if (Date.now() < programmaticScrollUntilRef.current) {
        return;
      }
      if (nearBottom) {
        if (!autoFollowRef.current) {
          setAutoFollow(true);
        }
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
    if (currentSessionId) {
      onSessionCreated(currentSessionId);
    }
  }, [currentSessionId, onSessionCreated]);

  useEffect(() => {
    if (!deferredSearch.trim()) {
      setAnchorEntryId(null);
    }
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
        if (cancelled) {
          return;
        }
        startTransition(() => {
          setEntries((prev) => {
            if (page === 1) {
              return data.entries;
            }
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
    if (!container || !autoFollow) {
      return;
    }
    scrollToBottom("smooth");
    setIsAtBottom(true);
    markLatestAsRead();
  }, [messages.length, status, autoFollow]);

  useEffect(() => {
    if (initialViewportSettledRef.current || loading || !autoFollow) {
      return;
    }
    if (deferredSearch.trim() || focusSessionId || anchorEntryId) {
      return;
    }
    if (hydratedEntries.length === 0 && messages.length === 0) {
      return;
    }
    initialViewportSettledRef.current = true;
    clearInitialViewportTimeout();
    // Use rAF to ensure the browser has laid out all rendered items before scrolling.
    // A plain setTimeout(0) can fire before layout is complete on large feeds.
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
    if (!latestItemId) {
      return;
    }
    if (!lastReadItemIdRef.current) {
      lastReadItemIdRef.current = latestItemId;
      return;
    }
    if (latestItemId === lastReadItemIdRef.current) {
      return;
    }
    if (autoFollow && isAtBottom) {
      markLatestAsRead(latestItemId);
      return;
    }
    const previousIndex = mergedItems.findIndex((item) => item.id === lastReadItemIdRef.current);
    const nextUnreadId = mergedItems[Math.max(previousIndex + 1, 0)]?.id ?? latestItemId;
    setFirstUnreadItemId((current) => current ?? nextUnreadId);
  }, [latestItemId, mergedItems, autoFollow, isAtBottom]);

  useEffect(() => {
    if (!autoFollow) {
      return;
    }
    const hasLiveWork = hydratedEntries.some((entry) => entry.status === "active" || entry.live_status === "active");
    if (!hasLiveWork) {
      return;
    }
    const container = scrollRef.current;
    if (!container || !isNearBottom(container)) {
      return;
    }
    scrollToBottom("smooth");
    setIsAtBottom(true);
    markLatestAsRead();
  }, [autoFollow, hydratedEntries]);

  useEffect(() => {
    const container = scrollRef.current;
    const anchor = olderHistoryAnchorRef.current;
    if (!container || !anchor || loading) {
      return;
    }
    const heightDelta = container.scrollHeight - anchor.scrollHeight;
    container.scrollTop = anchor.scrollTop + Math.max(heightDelta, 0);
    olderHistoryAnchorRef.current = null;
  }, [entries, loading]);

  useEffect(() => {
    const hasLiveWork = hydratedEntries.some((entry) => entry.status === "active" || entry.live_status === "active");
    if (!hasLiveWork || liveEventsStatus === "connected") {
      return;
    }
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
        if (pendingRoutine.length === 0) {
          return;
        }
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
            firstUnreadItemId
            && block.items.some(
              ({ anchorItem, childRuns }) =>
                anchorItem.id === firstUnreadItemId || childRuns.some((childRun) => childRun.id === firstUnreadItemId),
            ),
          );
          if (containsUnread) {
            rows.push({ kind: "unread", id: `unread:${block.id}` });
          }
          rows.push({ kind: "routine_group", id: block.id, block });
          continue;
        }
        if (
          firstUnreadItemId
          && (block.anchorItem.id === firstUnreadItemId || block.childRuns.some((childRun) => childRun.id === firstUnreadItemId))
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
        row.childRuns.forEach((childRun) => indexMap.set(childRun.id, index));
        return;
      }
      if (row.kind === "routine_group") {
        row.block.items.forEach(({ anchorItem, childRuns }) => {
          indexMap.set(anchorItem.id, index);
          childRuns.forEach((childRun) => indexMap.set(childRun.id, index));
        });
      }
    });
    return indexMap;
  }, [timelineRows]);

  const rowIndexBySessionId = useMemo(() => {
    const indexMap = new Map<string, number>();
    timelineRows.forEach((row, index) => {
      if (row.kind === "item") {
        if (row.item.sessionId) {
          indexMap.set(row.item.sessionId, index);
        }
        row.childRuns.forEach((childRun) => indexMap.set(childRun.sessionId, index));
        return;
      }
      if (row.kind === "routine_group") {
        row.block.items.forEach(({ anchorItem, childRuns }) => {
          indexMap.set(anchorItem.sessionId, index);
          childRuns.forEach((childRun) => indexMap.set(childRun.sessionId, index));
        });
      }
    });
    return indexMap;
  }, [timelineRows]);

  const virtualizer = useVirtualizer({
    count: timelineRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) => {
      const row = timelineRows[index];
      if (!row) {
        return 80;
      }
      if (row.kind === "divider") {
        return 56;
      }
      if (row.kind === "unread") {
        return 40;
      }
      if (row.kind === "routine_group") {
        return expandedRoutineGroupIds[row.block.id] ? 360 : 120;
      }
      const expanded = row.item.kind !== "message" && expandedEntryIds[row.item.id];
      const childRunCount = row.childRuns.length;
      return expanded ? 420 + childRunCount * 140 : 160 + childRunCount * 140;
    },
    overscan: 10,
  });

  const hasExpandedTimelineContent = useMemo(
    () =>
      Object.values(expandedEntryIds).some(Boolean)
      || Object.values(expandedRoutineGroupIds).some(Boolean),
    [expandedEntryIds, expandedRoutineGroupIds],
  );
  const virtualRows = virtualizer.getVirtualItems();
  const renderVirtualRows = false;
  const renderedRows = renderVirtualRows
    ? virtualRows.map((virtualRow) => ({
        key: virtualRow.key,
        row: timelineRows[virtualRow.index],
        start: virtualRow.start,
        measure: true,
      }))
    : timelineRows.map((row, index) => ({
        key: `${row.id}:${index}`,
        row,
        start: 0,
        measure: false,
      }));

  useEffect(() => {
    if (!focusSessionId) {
      return;
    }
    const rowIndex = rowIndexBySessionId.get(focusSessionId);
    if (rowIndex != null) {
      virtualizer.scrollToIndex(rowIndex, { align: "center" });
    }
    const timeout = window.setTimeout(() => {
      const nodes = document.querySelectorAll<HTMLElement>(`[data-session-anchor="${focusSessionId}"]`);
      const target = nodes.length > 0 ? nodes[nodes.length - 1] : null;
      target?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timeout);
  }, [entries, focusSessionId, rowIndexBySessionId, virtualizer]);

  const filterCounts = useMemo(() => {
    const counts: Record<FilterMode, number> = {
      all: hydratedEntries.length + messages.length,
      messages: [...hydratedEntries.filter((entry) => entry.entry_type === "message"), ...messages].length,
      work: hydratedEntries.filter((entry) => entry.entry_type === "heartbeat" || entry.entry_type === "child_run").length,
      heartbeats: hydratedEntries.filter((entry) => entry.entry_type === "heartbeat").length,
      friction: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "friction")).length,
      errors: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "error")).length,
      warnings: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "warning")).length,
      stalled: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "stalled")).length,
      drift: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "instruction_drift")).length,
      tool_friction: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "tool_friction")).length,
      retries: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "retries")).length,
      recovered: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "recovered")).length,
      escalations: hydratedEntries.filter((entry) => entryHasPulseTag(entry, "escalation")).length,
    };
    return counts;
  }, [hydratedEntries, messages]);

  const newActivityCount = useMemo(() => {
    if (!firstUnreadItemId) {
      return 0;
    }
    const unreadIndex = mergedItems.findIndex((item) => item.id === firstUnreadItemId);
    if (unreadIndex < 0) {
      return 0;
    }
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

    if (searchMatches.length === 0) {
      return;
    }
    if (!activeSearchMatchId || !searchMatches.some((item) => item.entry_id === activeSearchMatchId)) {
      setActiveSearchMatchId(searchMatches[0]?.entry_id ?? null);
    }
  }, [deferredSearch, searchMatches, activeSearchMatchId]);

  useEffect(() => {
    if (!activeMatchId) {
      return;
    }
    if (hydratedEntries.some((entry) => entry.id === activeMatchId && entry.entry_type !== "message")) {
      setExpandedEntryIds((current) => (
        current[activeMatchId]
          ? current
          : {
              ...current,
              [activeMatchId]: true,
            }
      ));
    }
    const loaded = mergedItems.some((item) => item.id === activeMatchId);
    if (!loaded && anchorEntryId !== activeMatchId) {
      setAnchorEntryId(activeMatchId);
      return;
    }
    const rowIndex = rowIndexByStreamItemId.get(activeMatchId);
    if (rowIndex != null) {
      virtualizer.scrollToIndex(rowIndex, { align: "center" });
    }
    const timeout = window.setTimeout(() => {
      const node = document.querySelector<HTMLElement>(`[data-stream-item-id="${activeMatchId}"]`);
      node?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timeout);
  }, [activeMatchId, mergedItems, anchorEntryId, rowIndexByStreamItemId, virtualizer]);

  const handleSessionJump = (sessionId: string | null) => {
    onSelectSession(sessionId);
    setFocusSessionId(sessionId);
    setAnchorEntryId(null);
    setAutoFollow(false);
  };

  const toggleExpanded = (entryId: string, sessionId?: string, externalId?: string) => {
    const willExpand = !expandedEntryIds[entryId];
    if (willExpand && sessionId) {
      void loadSessionEventDetails(sessionId);
    }
    if (willExpand && externalId) {
      void fetchNarrationTags(externalId);
    }
    setExpandedEntryIds((current) => ({
      ...current,
      [entryId]: !current[entryId],
    }));
  };

  const toggleRoutineGroup = (groupId: string) => {
    setExpandedRoutineGroupIds((current) => ({
      ...current,
      [groupId]: !current[groupId],
    }));
  };

  const visibleSearchMatches = useMemo(() => {
    if (searchMatches.length === 0) {
      return [];
    }
    if (activeSearchMatch < 0) {
      return searchMatches.slice(0, 5);
    }
    const start = Math.max(activeSearchMatch - 2, 0);
    const end = Math.min(start + 5, searchMatches.length);
    return searchMatches.slice(Math.max(end - 5, 0), end);
  }, [searchMatches, activeSearchMatch]);

  const jumpToSearchMatch = (direction: 1 | -1) => {
    if (searchMatches.length === 0) {
      return;
    }
    const currentIndex = searchMatches.findIndex((item) => item.entry_id === activeMatchId);
    const fallbackIndex = 0;
    const resolvedIndex = currentIndex >= 0 ? currentIndex : fallbackIndex;

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

  const visiblePulseMetrics = useMemo(
    () => pulse.metrics.filter((metric) => metric.count > 0 || metric.key === "friction"),
    [pulse.metrics],
  );
  const activeIssueTag = filterMode === "friction" ? "friction" : filterModeToPulseTag(filterMode);

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

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      {/* ── Toolbar ── */}
      <div className="border-b border-slate-800/50 bg-[#0d0e13]/95 backdrop-blur-lg px-5 py-2.5">
        <div className="flex items-center gap-2.5">
          <div className="relative flex-1 min-w-0">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
            <input
              id={searchInputId}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setAnchorEntryId(null);
              }}
              placeholder="Search history, tasks, files, agents..."
              className="w-full rounded-lg border border-slate-700/50 bg-slate-900/60 py-2 pl-9 pr-3 text-xs text-slate-200 outline-none transition-all placeholder:text-slate-600 focus:border-amber-500/30 focus:bg-slate-900/80 focus:ring-1 focus:ring-amber-500/20"
            />
          </div>
          <TimeRangeDropdown value={timeRange} onChange={setTimeRange} />
          <button
            type="button"
            onClick={() => setShowFilters((v) => !v)}
            className={cn(
              "inline-flex items-center gap-1 rounded-lg p-2 text-xs transition-all",
              showFilters || filterMode !== "all"
                ? "bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/20"
                : "text-slate-500 hover:bg-slate-800/60 hover:text-slate-300",
            )}
            title="Toggle filters"
          >
            <Filter className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Active filter indicator */}
        {filterMode !== "all" && !showFilters && (
          <div className="mt-2 flex items-center gap-2">
            <span className="text-[10px] text-slate-600">Showing:</span>
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500/10 ring-1 ring-amber-500/20 px-2.5 py-1 text-[10px] font-medium text-amber-300">
              {filterMode} ({filterCounts[filterMode]})
              <button type="button" onClick={() => setFilterMode("all")} className="ml-0.5 text-amber-500/50 hover:text-amber-300 transition-colors">
                <X className="h-3 w-3" />
              </button>
            </span>
          </div>
        )}

        {/* Collapsible filter pills */}
        {showFilters && (
          <div className="mt-2.5 flex flex-wrap items-center gap-2 pb-1">
            {([
              ["all", "All"],
              ["messages", "Messages"],
              ["work", "Work"],
              ["heartbeats", "Heartbeats"],
              ...(filterCounts.friction > 0 ? [["friction", "Friction"]] : []),
              ...(filterCounts.errors > 0 ? [["errors", "Errors"]] : []),
              ...(filterCounts.warnings > 0 ? [["warnings", "Warnings"]] : []),
              ...(filterCounts.stalled > 0 ? [["stalled", "Stalled"]] : []),
              ...(filterCounts.drift > 0 ? [["drift", "Drift"]] : []),
              ...(filterCounts.tool_friction > 0 ? [["tool_friction", "Tool Friction"]] : []),
              ...(filterCounts.retries > 0 ? [["retries", "Retries"]] : []),
              ...(filterCounts.recovered > 0 ? [["recovered", "Recovered"]] : []),
              ...(filterCounts.escalations > 0 ? [["escalations", "Escalations"]] : []),
            ] as Array<[FilterMode, string]>).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => { setFilterMode(value); setShowFilters(false); }}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition-all",
                  filterMode === value
                    ? "bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30"
                    : "bg-slate-800/40 text-slate-500 hover:bg-slate-800/60 hover:text-slate-300",
                )}
              >
                {label}
                {value !== "all" && <span className="opacity-60">{filterCounts[value]}</span>}
              </button>
            ))}
          </div>
        )}

        {/* Search results bar */}
        {deferredSearch.trim() && (
          <div className="mt-2 flex items-center justify-between gap-2 rounded-lg border border-slate-700/40 bg-slate-900/60 px-3.5 py-2 text-xs text-slate-400">
            <span>
              {matchCount === 0
                ? `No matches for "${deferredSearch.trim()}"`
                : `${Math.max(activeSearchMatch, 0) + 1} of ${matchCount} matches`}
            </span>
            {matchCount > 0 && (
              <div className="flex items-center gap-0.5">
                <button type="button" onClick={() => jumpToSearchMatch(-1)} className="rounded-md p-1.5 transition-colors hover:bg-slate-800/80 hover:text-slate-200">
                  <ArrowUp className="h-3.5 w-3.5" />
                </button>
                <button type="button" onClick={() => jumpToSearchMatch(1)} className="rounded-md p-1.5 transition-colors hover:bg-slate-800/80 hover:text-slate-200">
                  <ArrowDown className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </div>
        )}
        {deferredSearch.trim() && visibleSearchMatches.length > 0 && (
          <div className="mt-2.5 flex flex-wrap gap-2">
            {visibleSearchMatches.map((match) => (
              <button
                key={match.entry_id}
                type="button"
                onClick={() => {
                  setActiveSearchMatchId(match.entry_id);
                  setAnchorEntryId(match.entry_id);
                  setAutoFollow(false);
                }}
                className={cn(
                  "max-w-full rounded-xl border px-3 py-2 text-left text-[11px] transition-all",
                  match.entry_id === activeMatchId
                    ? "border-amber-600/40 bg-amber-950/20 text-amber-100 shadow-sm shadow-amber-900/10"
                    : "border-slate-800/40 bg-slate-900/30 text-slate-400 hover:border-slate-700/50 hover:bg-slate-800/30",
                )}
              >
                <span className="font-medium uppercase tracking-wider text-[9px] text-slate-600">
                  {formatTimeLabel(new Date(match.timestamp))} · {match.entry_type}
                </span>
                <HighlightedText text={shortenText(match.snippet, 90)} className="mt-0.5 block" />
              </button>
            ))}
          </div>
        )}
      </div>

      <div ref={scrollRef} data-testid="stream-scroll-container" className="flex-1 overflow-y-auto px-5 py-5 bg-[#0a0b0f]">
        <div className="mx-auto max-w-3xl">
          <PulseOverviewPanels
            visiblePulseMetrics={visiblePulseMetrics}
            pulse={pulse}
            applyPulseFilter={applyPulseFilter}
            inspectAgentPulse={inspectAgentPulse}
          />
        </div>

        {(error || chatError) && (
          <div className="mb-4 flex items-center gap-2.5 rounded-xl border border-rose-500/20 bg-rose-950/20 px-4 py-2.5 text-sm text-rose-300/90">
            <AlertCircle className="h-4 w-4 flex-shrink-0 text-rose-400" />
            {error || chatError}
          </div>
        )}

        {loading && entries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-slate-500 gap-3">
            <Loader2 className="h-5 w-5 animate-spin text-amber-500/60" />
            <span className="text-xs text-slate-600">Loading activity...</span>
          </div>
        ) : groupedItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 gap-3">
            <div className="rounded-full bg-slate-800/50 p-4">
              <HeartPulse className="h-6 w-6 text-slate-600" />
            </div>
            <p className="text-sm font-medium text-slate-500">No activity yet</p>
            <p className="text-xs text-slate-600 max-w-xs text-center">
              {personaDisplayName} hasn&apos;t had any heartbeats or conversations in this time range.
            </p>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl">
            <div
              className="relative w-full space-y-1.5"
              style={renderVirtualRows ? { height: `${virtualizer.getTotalSize()}px` } : undefined}
            >
              {renderedRows.map(({ key, row, start, measure }) => {
                if (!row) {
                  return null;
                }
                if (row.kind === "divider") {
                  return (
                    <div
                      key={key}
                      ref={measure ? virtualizer.measureElement : undefined}
                      className={cn(renderVirtualRows && "absolute left-0 top-0 w-full")}
                      style={renderVirtualRows ? { transform: `translateY(${start}px)` } : undefined}
                    >
                      <DateDivider label={row.label} />
                    </div>
                  );
                }
                if (row.kind === "unread") {
                  return (
                    <div
                      key={key}
                      ref={measure ? virtualizer.measureElement : undefined}
                      className={cn(renderVirtualRows && "absolute left-0 top-0 w-full")}
                      style={renderVirtualRows ? { transform: `translateY(${start}px)` } : undefined}
                    >
                      <div
                        data-testid="new-activity-separator"
                        className="flex items-center gap-3 py-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-amber-400/80"
                      >
                        <div className="h-px flex-1 bg-gradient-to-r from-transparent to-amber-500/20" />
                        <span className="inline-flex items-center gap-1.5 rounded-md bg-amber-500/10 px-2.5 py-1">
                          <CircleDot className="h-3 w-3" />
                          New activity
                        </span>
                        <div className="h-px flex-1 bg-gradient-to-l from-transparent to-amber-500/20" />
                      </div>
                    </div>
                  );
                }
                if (row.kind === "routine_group") {
                  return (
                    <div
                      key={key}
                      ref={measure ? virtualizer.measureElement : undefined}
                      className={cn(renderVirtualRows && "absolute left-0 top-0 w-full")}
                      style={renderVirtualRows ? { transform: `translateY(${start}px)` } : undefined}
                    >
                      <RoutineHeartbeatGroup
                        block={row.block}
                        expanded={!!expandedRoutineGroupIds[row.block.id]}
                        onToggle={() => toggleRoutineGroup(row.block.id)}
                        activeSessionId={selectedSessionId}
                        activeIssueTag={activeIssueTag}
                        expandedEntryIds={expandedEntryIds}
                        onToggleEntry={(entryId, sessionId) => {
                          const entry = row.block.items.find((it) => it.anchorItem.id === entryId);
                          toggleExpanded(entryId, sessionId, entry?.anchorItem.entry.external_id ?? undefined);
                        }}
                        sessionEventDetails={sessionEventDetails}
                        narrationCache={narrationCache}
                        onFetchNarration={fetchNarrationTags}
                        personaName={personaDisplayName}
                      />
                    </div>
                  );
                }

                const item = row.item;
                const selected = !!item.sessionId && item.sessionId === selectedSessionId;
                const matched = matchedIds.has(item.id);
                const activeMatched = activeMatchId === item.id;
                const baseClasses = cn(
                  "flex items-start gap-3 rounded-xl",
                  matched && "px-2.5 py-1.5 ring-1 ring-amber-600/30 bg-amber-950/5",
                  activeMatched && "ring-2 ring-amber-500/50 bg-amber-950/10",
                );

                return (
                  <div
                    key={key}
                    ref={measure ? virtualizer.measureElement : undefined}
                    className={cn(renderVirtualRows && "absolute left-0 top-0 w-full")}
                    style={renderVirtualRows ? { transform: `translateY(${start}px)` } : undefined}
                  >
                    {item.kind === "message" ? (
                      <div
                        data-session-anchor={item.sessionId ?? undefined}
                        data-testid="stream-item"
                        data-stream-item-id={item.id}
                        data-timestamp={item.timestamp.toISOString()}
                        className={cn(
                          "flex items-start gap-3",
                          selected && "rounded-xl bg-sky-950/10 px-2.5 py-1.5",
                          matched && "rounded-xl px-2.5 py-1.5 ring-1 ring-amber-600/30 bg-amber-950/5",
                          activeMatched && "ring-2 ring-amber-500/50 bg-amber-950/10",
                        )}
                      >
                        <TimelineTimestamp timestamp={item.timestamp} />
                        <div className="min-w-0 flex-1">
                          <MessageBubble
                            message={item.message}
                            isStreaming={status !== "idle" && status !== "error"}
                            canEdit={false}
                            canRegenerate={false}
                          />
                          {row.childRuns.length > 0 && (
                            <ChildRunStack
                              childRuns={row.childRuns}
                              activeSessionId={selectedSessionId}
                              activeIssueTag={activeIssueTag}
                              expandedEntryIds={expandedEntryIds}
                              onToggle={(entryId, sessionId) => {
                                const cr = row.childRuns.find((c) => c.id === entryId);
                                toggleExpanded(entryId, sessionId, cr?.entry.external_id ?? undefined);
                              }}
                              matchedIds={matchedIds}
                              activeMatchId={activeMatchId}
                              sessionEventDetails={sessionEventDetails}
                              narrationCache={narrationCache}
                              onFetchNarration={fetchNarrationTags}
                              personaName={personaDisplayName}
                            />
                          )}
                        </div>
                      </div>
                    ) : item.kind === "child_run" ? (
                      <div
                        data-session-anchor={item.sessionId}
                        data-testid="stream-item"
                        data-stream-item-id={item.id}
                        data-timestamp={item.timestamp.toISOString()}
                        className={baseClasses}
                      >
                        <TimelineTimestamp timestamp={item.timestamp} />
                        <div className="min-w-0 flex-1">
                          <ChildRunCard
                            entry={item.entry}
                            activeIssueTag={activeIssueTag}
                            selected={selected}
                            expanded={!!expandedEntryIds[item.id]}
                            onToggle={() => toggleExpanded(item.id, item.sessionId, item.entry.external_id ?? undefined)}
                            details={sessionEventDetails[item.sessionId]}
                            narrationTags={item.entry.external_id ? narrationCache[item.entry.external_id]?.tags : undefined}
                            narrationLoading={item.entry.external_id ? narrationCache[item.entry.external_id]?.loading : undefined}
                            personaName={personaDisplayName}
                          />
                        </div>
                      </div>
                    ) : (
                      <div
                        data-session-anchor={item.sessionId}
                        data-testid="stream-item"
                        data-stream-item-id={item.id}
                        data-timestamp={item.timestamp.toISOString()}
                        className={baseClasses}
                      >
                        <TimelineTimestamp timestamp={item.timestamp} />
                        <div className="min-w-0 flex-1">
                          <HeartbeatCard
                            entry={item.entry}
                            activeIssueTag={activeIssueTag}
                            selected={selected}
                            expanded={!!expandedEntryIds[item.id]}
                            onToggle={() => toggleExpanded(item.id, item.sessionId, item.entry.external_id ?? undefined)}
                            details={sessionEventDetails[item.sessionId]}
                            narrationTags={item.entry.external_id ? narrationCache[item.entry.external_id]?.tags : undefined}
                            narrationLoading={item.entry.external_id ? narrationCache[item.entry.external_id]?.loading : undefined}
                            personaName={personaDisplayName}
                          />
                          {row.childRuns.length > 0 && (
                            <ChildRunStack
                              childRuns={row.childRuns}
                              activeSessionId={selectedSessionId}
                              activeIssueTag={activeIssueTag}
                              expandedEntryIds={expandedEntryIds}
                              onToggle={(entryId, sessionId) => {
                                const cr = row.childRuns.find((c) => c.id === entryId);
                                toggleExpanded(entryId, sessionId, cr?.entry.external_id ?? undefined);
                              }}
                              matchedIds={matchedIds}
                              activeMatchId={activeMatchId}
                              sessionEventDetails={sessionEventDetails}
                              narrationCache={narrationCache}
                              onFetchNarration={fetchNarrationTags}
                              personaName={personaDisplayName}
                            />
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {total > entries.length && !deferredSearch.trim() && (
              <div className="flex justify-center pt-8 pb-2">
                <button
                  onClick={() => {
                    const container = scrollRef.current;
                    if (container) {
                      olderHistoryAnchorRef.current = {
                        scrollHeight: container.scrollHeight,
                        scrollTop: container.scrollTop,
                      };
                    }
                    setPage((value) => value + 1);
                  }}
                  className="rounded-lg border border-slate-700/50 bg-slate-800/40 px-5 py-2.5 text-xs font-medium text-slate-400 transition-all hover:bg-slate-800/70 hover:text-slate-200 hover:border-slate-600/50"
                >
                  Load older entries
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {(latestItemId && (!isAtBottom || !autoFollow || newActivityCount > 0)) && (
        <div className="pointer-events-none absolute bottom-24 right-6 z-20">
          <button
            type="button"
            onClick={() => {
              setAutoFollow(true);
              scrollToBottom("smooth");
              setIsAtBottom(true);
              markLatestAsRead();
            }}
            className="pointer-events-auto inline-flex items-center gap-2 rounded-full bg-slate-800 px-3.5 py-2 text-xs font-medium text-slate-200 shadow-lg shadow-black/30 ring-1 ring-slate-700 transition hover:bg-slate-700 hover:text-white"
          >
            <ArrowDown className="h-4 w-4" />
            {newActivityCount > 0 ? `${newActivityCount} new ${newActivityCount === 1 ? "item" : "items"} · Jump to latest` : "Jump to latest"}
          </button>
        </div>
      )}

      <div className="border-t border-slate-800/50 bg-[#0d0e13]/95 px-5 py-3 backdrop-blur-lg">
        <div className="mx-auto max-w-3xl">
          <div className="mb-2 flex items-center justify-between text-[11px] text-slate-500">
            <div className="flex items-center gap-2">
              {responseStatusLabel && (
                <span className="inline-flex items-center gap-1.5 text-amber-400/80">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {responseStatusLabel}
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={onNewSession}
              className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-slate-600 transition-all hover:bg-slate-800/50 hover:text-slate-400"
            >
              <MessageSquarePlus className="h-3 w-3" />
              New thread
            </button>
          </div>
          <MessageInput
            onSend={sendMessage}
            onCancel={cancelStream}
            status={status}
            voiceWsUrl={getWsUrl("/api/voice/ws?user_id=agent_hub_user&app=agent-hub&mode=transcribe")}
            ttsBaseUrl={getApiBaseUrl() || window.location.origin}
            preferencesEndpoint={apiConfig.preferencesEndpoint}
            fetchFn={fetchApi}
          />
        </div>
      </div>
    </div>
  );
}
