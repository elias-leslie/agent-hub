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
  Loader2,
  Radio,
  Search,
  Sparkles,
} from "lucide-react";
import {
  MessageBubble,
  MessageInput,
  useChatStream,
  type ChatMessage,
} from "@agent-hub/chat-ui";

import { SessionDropdown } from "@/components/chat/session-dropdown";
import { useSessionEvents } from "@/hooks/use-session-events";
import { cn } from "@/lib/utils";
import { INTERNAL_HEADERS, fetchApi, getApiBaseUrl, getSseBaseUrl, getWsUrl } from "@/lib/api-config";
import { fetchSessionEvents } from "@/lib/api/sessions";
import {
  type PersonaStreamMatch,
  type PersonaPulseSummary,
  fetchPersonaStream,
  type PersonaStreamEntry,
} from "@/lib/api/persona-stream";
import type { SessionEvent as LiveSessionEvent, TimelineEvent } from "@/types/events";
import { TimeRangeDropdown, type TimeRange } from "./TimeRangeDropdown";
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
  ExpandableText,
  HighlightedText,
  TimelineTimestamp,
  entryStatusClasses,
  formatDayLabel,
  formatTimeLabel,
  heartbeatIsImportant,
  isGenericStatusText,
  isNearBottom,
  shortenText,
  shouldRenderPulseSummary,
} from "./workspace-utils";
import { mergeEventPreviews, buildLivePreview, liveSummaryFromEvent, liveStatusFromEvent, isRoutineHeartbeatBlock } from "./workspace-live-events";
import {
  ChildRunCard,
  ChildRunStack,
  EntryIssueSummary,
  HeartbeatCard,
  PulseOverviewPanels,
  RoutineHeartbeatGroup,
} from "./workspace-cards";

interface UnifiedPersonaWorkspaceProps {
  agentSlug: string;
  activeSessionId: string | null;
  sidebarRefreshTrigger: number;
  runtimeSyncKey: string;
  onSelectSession: (sessionId: string | null) => void;
  onSessionCreated: (sessionId: string) => void;
  onNewSession: () => void;
}

export function UnifiedPersonaWorkspace({
  agentSlug,
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
      completeEndpoint: `${getSseBaseUrl()}/api/complete`,
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
    loadInitialSession: false,
  });

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
    const remote = buildRemoteFeedItems([...hydratedEntries].reverse());
    const local = buildLocalFeedMessages(messages, currentSessionId || activeSessionId);
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
        });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load stream");
          setPulse(EMPTY_PULSE);
        }
      })
      .finally(() => {
        if (!cancelled) {
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
    initialViewportTimeoutRef.current = window.setTimeout(() => {
      scrollToBottom("auto");
      setIsAtBottom(true);
      markLatestAsRead();
      initialViewportTimeoutRef.current = null;
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

  const toggleExpanded = (entryId: string, sessionId?: string) => {
    const willExpand = !expandedEntryIds[entryId];
    if (willExpand && sessionId) {
      void loadSessionEventDetails(sessionId);
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
      <div className="border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <div className="flex flex-wrap items-center gap-2">
          <SessionDropdown
            activeSessionId={selectedSessionId}
            onSelectSession={handleSessionJump}
            onNewSession={onNewSession}
            projectId={PROJECT_ID}
            agentSlug={agentSlug}
            refreshTrigger={sidebarRefreshTrigger}
          />
          <div className="relative min-w-[18rem] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              id={searchInputId}
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setAnchorEntryId(null);
              }}
              placeholder="Search Jenny's history, task IDs, files, agents..."
              className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-sm text-slate-700 outline-none transition focus:border-sky-300 focus:bg-white dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-700"
            />
          </div>
          <TimeRangeDropdown value={timeRange} onChange={setTimeRange} />
          <button
            type="button"
            onClick={() => {
              setAutoFollow((value) => {
                const next = !value;
                if (next) {
                  window.setTimeout(() => {
                    scrollToBottom("smooth");
                    setIsAtBottom(true);
                    markLatestAsRead();
                  }, 0);
                }
                return next;
              });
            }}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-medium transition",
              autoFollow
                ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-800"
                : "bg-slate-100 text-slate-600 ring-1 ring-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-700",
            )}
          >
            <Radio className="h-4 w-4" />
            {autoFollow ? "Auto-follow on" : "Auto-follow off"}
          </button>
        </div>
        <div className="mt-2 text-[11px] text-slate-400 dark:text-slate-500">
          Search everything, or use prefixes like <span className="font-semibold">task:</span>, <span className="font-semibold">file:</span>, <span className="font-semibold">agent:</span>, <span className="font-semibold">status:</span>, and <span className="font-semibold">project:</span>.
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {([
            ["all", "All"],
            ["messages", "Messages"],
            ["work", "Work"],
            ["heartbeats", "Heartbeats"],
            ["friction", "Friction"],
            ["errors", "Errors"],
            ["warnings", "Warnings"],
            ["stalled", "Stalled"],
            ["drift", "Drift"],
            ["tool_friction", "Tool Friction"],
            ["retries", "Retries"],
            ["recovered", "Recovered"],
            ["escalations", "Escalations"],
          ] as Array<[FilterMode, string]>).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setFilterMode(value)}
              className={cn(
                "inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition",
                filterMode === value
                  ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
                  : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800",
              )}
            >
              {label}
              <span className="opacity-70">{filterCounts[value]}</span>
            </button>
          ))}
        </div>
        {deferredSearch.trim() && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
            <span>
              {matchCount === 0
                ? `No matches for "${deferredSearch.trim()}"`
                : `${Math.max(activeSearchMatch, 0) + 1} of ${matchCount} matches for "${deferredSearch.trim()}"`}
            </span>
            {matchCount > 0 && (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => jumpToSearchMatch(-1)}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-white dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  <ArrowUp className="h-3.5 w-3.5" />
                  Prev match
                </button>
                <button
                  type="button"
                  onClick={() => jumpToSearchMatch(1)}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-white dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  <ArrowDown className="h-3.5 w-3.5" />
                  Next match
                </button>
              </div>
            )}
          </div>
        )}
        {deferredSearch.trim() && visibleSearchMatches.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
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
                  "max-w-full rounded-2xl border px-3 py-2 text-left text-xs transition",
                  match.entry_id === activeMatchId
                    ? "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-100"
                    : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300 dark:hover:bg-slate-900",
                )}
              >
                <div className="font-semibold uppercase tracking-[0.14em] text-[10px] opacity-70">
                  {formatTimeLabel(new Date(match.timestamp))} · {match.entry_type}
                </div>
                <HighlightedText text={shortenText(match.snippet, 90)} className="mt-1 block" />
              </button>
            ))}
          </div>
        )}
      </div>

      <div ref={scrollRef} data-testid="stream-scroll-container" className="flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto max-w-4xl">
          <PulseOverviewPanels
            visiblePulseMetrics={visiblePulseMetrics}
            pulse={pulse}
            applyPulseFilter={applyPulseFilter}
            inspectAgentPulse={inspectAgentPulse}
          />
        </div>

        {(error || chatError) && (
          <div className="mb-4 flex items-center gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-300">
            <AlertCircle className="h-4 w-4" />
            {error || chatError}
          </div>
        )}

        {loading && entries.length === 0 ? (
          <div className="flex items-center justify-center py-20 text-slate-400">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : groupedItems.length === 0 ? (
          <div className="py-20 text-center text-slate-500 dark:text-slate-400">
            No stream entries yet.
          </div>
        ) : (
          <div className="mx-auto max-w-4xl">
            <div
              className="relative w-full"
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
                        className="flex items-center gap-3 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-sky-600 dark:text-sky-300"
                      >
                        <div className="h-px flex-1 bg-sky-200 dark:bg-sky-900" />
                        <span className="inline-flex items-center gap-1">
                          <CircleDot className="h-3.5 w-3.5" />
                          New since you scrolled away
                        </span>
                        <div className="h-px flex-1 bg-sky-200 dark:bg-sky-900" />
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
                        onToggleEntry={toggleExpanded}
                        sessionEventDetails={sessionEventDetails}
                      />
                    </div>
                  );
                }

                const item = row.item;
                const selected = !!item.sessionId && item.sessionId === selectedSessionId;
                const matched = matchedIds.has(item.id);
                const activeMatched = activeMatchId === item.id;
                const baseClasses = cn(
                  "flex items-start gap-3 rounded-2xl",
                  matched && "px-2 py-1 ring-1 ring-amber-200 dark:ring-amber-800",
                  activeMatched && "ring-2 ring-amber-400 dark:ring-amber-500",
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
                          selected && "rounded-2xl bg-sky-50/40 px-2 py-1 dark:bg-sky-950/10",
                          matched && "rounded-2xl px-2 py-1 ring-1 ring-amber-200 dark:ring-amber-800",
                          activeMatched && "ring-2 ring-amber-400 dark:ring-amber-500",
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
                              onToggle={toggleExpanded}
                              matchedIds={matchedIds}
                              activeMatchId={activeMatchId}
                              sessionEventDetails={sessionEventDetails}
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
                            onToggle={() => toggleExpanded(item.id, item.sessionId)}
                            details={sessionEventDetails[item.sessionId]}
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
                            onToggle={() => toggleExpanded(item.id, item.sessionId)}
                            details={sessionEventDetails[item.sessionId]}
                          />
                          {row.childRuns.length > 0 && (
                            <ChildRunStack
                              childRuns={row.childRuns}
                              activeSessionId={selectedSessionId}
                              activeIssueTag={activeIssueTag}
                              expandedEntryIds={expandedEntryIds}
                              onToggle={toggleExpanded}
                              matchedIds={matchedIds}
                              activeMatchId={activeMatchId}
                              sessionEventDetails={sessionEventDetails}
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
              <div className="flex justify-center pt-6">
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
                  className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600 transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
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
            className="pointer-events-auto inline-flex items-center gap-2 rounded-full bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-lg transition hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
          >
            <ArrowDown className="h-4 w-4" />
            {newActivityCount > 0 ? `${newActivityCount} new ${newActivityCount === 1 ? "item" : "items"} · Jump to latest` : "Jump to latest"}
          </button>
        </div>
      )}

      <div className="border-t border-slate-200 bg-white/95 px-4 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-950/95">
        <div className="mx-auto max-w-4xl">
          <div className="mb-2 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
            <span className="inline-flex items-center gap-1">
              <Sparkles className="h-3.5 w-3.5" />
              Composer is attached to {activeSessionId ? `session ${activeSessionId.slice(0, 8)}` : "a new thread"}
            </span>
            {status !== "idle" && (
              <span className="inline-flex items-center gap-1 text-amber-600 dark:text-amber-300">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Jenny is responding
              </span>
            )}
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
