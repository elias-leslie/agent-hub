"use client";

import Link from "next/link";
import {
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
  startTransition,
} from "react";
import {
  Search,
  Loader2,
  HeartPulse,
  Wrench,
  Bot,
  Sparkles,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  ArrowDown,
  ArrowUp,
  Clock3,
} from "lucide-react";
import {
  MessageBubble,
  MessageInput,
  useChatStream,
  type ChatMessage,
} from "@agent-hub/chat-ui";

import { SessionDropdown } from "@/components/chat/session-dropdown";
import { cn } from "@/lib/utils";
import { INTERNAL_HEADERS, fetchApi, getApiBaseUrl, getSseBaseUrl, getWsUrl } from "@/lib/api-config";
import {
  fetchPersonaStream,
  type PersonaStreamEventPreview,
  type PersonaStreamEntry,
} from "@/lib/api/persona-stream";
import { TimeRangeDropdown, type TimeRange } from "./TimeRangeDropdown";

const PROJECT_ID = "persona-sandbox";
const PAGE_SIZE = 120;

interface UnifiedPersonaWorkspaceProps {
  agentSlug: string;
  activeSessionId: string | null;
  sidebarRefreshTrigger: number;
  onSelectSession: (sessionId: string | null) => void;
  onSessionCreated: (sessionId: string) => void;
  onNewSession: () => void;
}

type FeedMessage = { kind: "message"; id: string; sessionId: string | null; timestamp: Date; message: ChatMessage };
type FeedHeartbeat = {
  kind: "heartbeat";
  id: string;
  sessionId: string;
  timestamp: Date;
  entry: PersonaStreamEntry;
};
type FeedChildRun = {
  kind: "child_run";
  id: string;
  sessionId: string;
  timestamp: Date;
  entry: PersonaStreamEntry;
};
type FeedAnchor = FeedMessage | FeedHeartbeat | FeedChildRun;
type FeedItem = FeedAnchor;

interface TimelineBlock {
  anchorItem: FeedAnchor;
  childRuns: FeedChildRun[];
}

function isChildRunItem(item: FeedItem): item is FeedChildRun {
  return item.kind === "child_run";
}

function canAnchorChildRuns(item: FeedAnchor): item is FeedMessage | FeedHeartbeat {
  return item.kind !== "child_run";
}

function buildChatMessage(entry: PersonaStreamEntry): ChatMessage {
  return {
    id: entry.id,
    role: (entry.role as ChatMessage["role"]) || "assistant",
    content: entry.content || "",
    timestamp: new Date(entry.timestamp),
    agentName: entry.agent_slug || undefined,
    agentModel: entry.model || undefined,
    agentProvider: "claude",
  };
}

function buildLocalFeedMessages(messages: ChatMessage[], currentSessionId: string | null): FeedItem[] {
  return messages.map((message) => ({
    kind: "message" as const,
    id: message.id,
    sessionId: currentSessionId,
    timestamp: message.timestamp,
    message,
  }));
}

function buildRemoteFeedItems(entries: PersonaStreamEntry[]): FeedItem[] {
  return entries.map((entry) => {
    if (entry.entry_type === "message") {
      return {
        kind: "message" as const,
        id: entry.id,
        sessionId: entry.session_id,
        timestamp: new Date(entry.timestamp),
        message: buildChatMessage(entry),
      };
    }
    return {
      kind: entry.entry_type,
      id: entry.id,
      sessionId: entry.session_id,
      timestamp: new Date(entry.timestamp),
      entry,
    };
  });
}

function DateDivider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 py-4">
      <div className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
      <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
        {label}
      </span>
      <div className="h-px flex-1 bg-slate-200 dark:bg-slate-800" />
    </div>
  );
}

function formatDayLabel(date: Date): string {
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatTimeLabel(date: Date): string {
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatTimestampTitle(date: Date): string {
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function TimelineTimestamp({ timestamp }: { timestamp: Date }) {
  const label = formatTimeLabel(timestamp);
  const title = formatTimestampTitle(timestamp);

  return (
    <time
      dateTime={timestamp.toISOString()}
      title={title}
      className="shrink-0 pt-2 text-[11px] font-medium tabular-nums tracking-[0.08em] text-slate-400 dark:text-slate-500"
    >
      {label}
    </time>
  );
}

function formatDurationLabel(durationMs: number | null): string | null {
  if (durationMs == null) {
    return null;
  }
  if (durationMs < 1000) {
    return `${durationMs}ms`;
  }
  if (durationMs < 60_000) {
    return `${(durationMs / 1000).toFixed(1)}s`;
  }
  const minutes = Math.floor(durationMs / 60_000);
  const seconds = Math.floor((durationMs % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function eventLabel(eventType: string): string {
  return eventType.replaceAll("_", " ");
}

function entrySearchText(entry: PersonaStreamEntry): string {
  return [
    entry.content,
    entry.summary_oneliner,
    entry.live_summary,
    entry.agent_slug,
    entry.project_id,
    entry.external_id,
    entry.current_branch,
    entry.model,
    ...entry.event_previews.flatMap((preview) => [
      preview.tool_name,
      preview.content_preview,
      preview.tool_input_preview,
      preview.tool_output_preview,
      preview.model_used,
      preview.event_type,
    ]),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function eventToneClasses(eventType: string): string {
  if (eventType === "error") {
    return "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-300";
  }
  if (eventType === "tool_result") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/30 dark:text-emerald-300";
  }
  if (eventType === "tool_use") {
    return "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900 dark:bg-sky-950/30 dark:text-sky-300";
  }
  if (eventType === "thinking") {
    return "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700 dark:border-fuchsia-900 dark:bg-fuchsia-950/30 dark:text-fuchsia-300";
  }
  return "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-950/50 dark:text-slate-300";
}

function eventSummaryLabel(preview: PersonaStreamEventPreview): string {
  if (preview.event_type === "tool_use") {
    return "Tool call";
  }
  if (preview.event_type === "tool_result") {
    return "Tool result";
  }
  if (preview.event_type === "error") {
    return "Error";
  }
  if (preview.event_type === "thinking") {
    return "Reasoning";
  }
  return eventLabel(preview.event_type);
}

function PreviewCodeBlock({
  label,
  value,
}: {
  label: string;
  value: string | null;
}) {
  if (!value) {
    return null;
  }

  return (
    <div className="mt-2 rounded-xl border border-slate-200 bg-white/80 p-2 dark:border-slate-800 dark:bg-slate-900/80">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
        {label}
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs text-slate-700 dark:text-slate-200">
        {value}
      </pre>
    </div>
  );
}

function EventPreviewList({ previews }: { previews: PersonaStreamEventPreview[] }) {
  return (
    <div className="mt-3 space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
      {previews.map((preview) => {
        const duration = formatDurationLabel(preview.duration_ms);
        return (
          <div
            key={preview.id}
            className={cn("rounded-xl border px-3 py-2 text-sm", eventToneClasses(preview.event_type))}
          >
            <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.14em]">
              <span>{eventSummaryLabel(preview)}</span>
              <time dateTime={preview.created_at} className="inline-flex items-center gap-1 normal-case tracking-normal opacity-80">
                <Clock3 className="h-3 w-3" />
                {formatTimeLabel(new Date(preview.created_at))}
              </time>
              {preview.tool_name && <span className="normal-case tracking-normal font-medium">{preview.tool_name}</span>}
              {duration && <span className="normal-case tracking-normal opacity-80">{duration}</span>}
            </div>
            {preview.content_preview && (
              <p className="mt-2 whitespace-pre-wrap break-words text-sm">
                {preview.content_preview}
              </p>
            )}
            <PreviewCodeBlock label="Input" value={preview.tool_input_preview} />
            <PreviewCodeBlock label="Output" value={preview.tool_output_preview} />
          </div>
        );
      })}
    </div>
  );
}

function ChildRunStack({
  childRuns,
  activeSessionId,
  expandedEntryIds,
  onToggle,
  matchedIds,
  activeMatchId,
}: {
  childRuns: FeedChildRun[];
  activeSessionId: string | null;
  expandedEntryIds: Record<string, boolean>;
  onToggle: (entryId: string) => void;
  matchedIds: Set<string>;
  activeMatchId: string | null;
}) {
  return (
    <div className="ml-5 mt-3 border-l border-dashed border-sky-200 pl-4 dark:border-sky-900">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-600 dark:text-sky-300">
        Spawned Agents
      </div>
      <div className="space-y-3">
        {childRuns.map((childRun) => {
          const selected = childRun.sessionId === activeSessionId;
          const matched = matchedIds.has(childRun.id);
          const activeMatched = activeMatchId === childRun.id;

          return (
            <div
              key={childRun.id}
              data-session-anchor={childRun.sessionId}
              data-testid="stream-item"
              data-stream-item-id={childRun.id}
              data-timestamp={childRun.timestamp.toISOString()}
              className={cn(
                "flex items-start gap-3 rounded-2xl",
                matched && "px-2 py-1 ring-1 ring-amber-200 dark:ring-amber-800",
                activeMatched && "ring-2 ring-amber-400 dark:ring-amber-500",
              )}
            >
              <TimelineTimestamp timestamp={childRun.timestamp} />
              <div className="min-w-0 flex-1">
                <ChildRunCard
                  entry={childRun.entry}
                  selected={selected}
                  expanded={!!expandedEntryIds[childRun.id]}
                  onToggle={() => onToggle(childRun.id)}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ChildRunCard({
  entry,
  selected,
  expanded,
  onToggle,
}: {
  entry: PersonaStreamEntry;
  selected: boolean;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border px-4 py-3",
        selected
          ? "border-sky-300 bg-sky-50/70 dark:border-sky-700 dark:bg-sky-950/30"
          : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-full bg-sky-100 p-2 text-sky-700 dark:bg-sky-950/50 dark:text-sky-300">
          <Bot className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              {entry.agent_slug || "Agent"} on {entry.project_id}
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {entry.status}
            </span>
            {entry.tool_count > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                <Wrench className="h-3 w-3" />
                {entry.tool_count}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            {entry.summary_oneliner || entry.live_summary || "Child run activity"}
          </p>
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400 dark:text-slate-500">
            {entry.external_id && <span>task {entry.external_id}</span>}
            {entry.current_branch && <span>{entry.current_branch}</span>}
            <Link
              href={`/sessions/${entry.session_id}`}
              className="text-sky-600 transition hover:text-sky-500 dark:text-sky-300 dark:hover:text-sky-200"
            >
              open session
            </Link>
          </div>
          {entry.event_previews.length > 0 && (
            <button
              type="button"
              onClick={onToggle}
              className="mt-3 inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
              {expanded ? "Hide run details" : `Show run details (${entry.event_previews.length})`}
            </button>
          )}
          {expanded && <EventPreviewList previews={entry.event_previews} />}
        </div>
      </div>
    </div>
  );
}

function HeartbeatCard({
  entry,
  selected,
  expanded,
  onToggle,
}: {
  entry: PersonaStreamEntry;
  selected: boolean;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border px-4 py-3",
        selected
          ? "border-amber-300 bg-amber-50/80 dark:border-amber-700 dark:bg-amber-950/30"
          : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-full bg-amber-100 p-2 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300">
          <HeartPulse className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Heartbeat
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              {entry.status}
            </span>
            {entry.tool_count > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                <Wrench className="h-3 w-3" />
                {entry.tool_count}
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            {entry.summary_oneliner || entry.live_summary || "Routine check completed"}
          </p>
          {entry.live_summary && entry.summary_oneliner !== entry.live_summary && (
            <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
              {entry.live_summary}
            </p>
          )}
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400 dark:text-slate-500">
            <Link
              href={`/sessions/${entry.session_id}`}
              className="text-amber-700 transition hover:text-amber-600 dark:text-amber-300 dark:hover:text-amber-200"
            >
              open session
            </Link>
          </div>
          {entry.event_previews.length > 0 && (
            <button
              type="button"
              onClick={onToggle}
              className="mt-3 inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
              {expanded ? "Hide heartbeat details" : `Show heartbeat details (${entry.event_previews.length})`}
            </button>
          )}
          {expanded && <EventPreviewList previews={entry.event_previews} />}
        </div>
      </div>
    </div>
  );
}

export function UnifiedPersonaWorkspace({
  agentSlug,
  activeSessionId,
  sidebarRefreshTrigger,
  onSelectSession,
  onSessionCreated,
  onNewSession,
}: UnifiedPersonaWorkspaceProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [entries, setEntries] = useState<PersonaStreamEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [focusSessionId, setFocusSessionId] = useState<string | null>(activeSessionId);
  const [expandedEntryIds, setExpandedEntryIds] = useState<Record<string, boolean>>({});
  const [activeSearchMatchId, setActiveSearchMatchId] = useState<string | null>(null);
  const [pendingSearchDirection, setPendingSearchDirection] = useState<1 | -1 | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

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
  } as any);

  useEffect(() => {
    if (currentSessionId) {
      onSessionCreated(currentSessionId);
    }
  }, [currentSessionId, onSessionCreated]);

  useEffect(() => {
    setFocusSessionId(activeSessionId);
  }, [activeSessionId]);

  useEffect(() => {
    setPage(1);
  }, [timeRange, deferredSearch, focusSessionId, currentSessionId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const effectiveRange = deferredSearch.trim() ? "all" : timeRange;
    fetchPersonaStream({
      timeRange: effectiveRange,
      search: deferredSearch.trim() || undefined,
      focusSessionId,
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
          setError(null);
        });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load stream");
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
  }, [timeRange, deferredSearch, focusSessionId, page, currentSessionId, sidebarRefreshTrigger]);

  useEffect(() => {
    if (!focusSessionId) {
      return;
    }
    const timeout = window.setTimeout(() => {
      const nodes = document.querySelectorAll<HTMLElement>(`[data-session-anchor="${focusSessionId}"]`);
      const target = nodes.length > 0 ? nodes[nodes.length - 1] : null;
      target?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timeout);
  }, [entries, focusSessionId]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container || typeof container.scrollTo !== "function") {
      return;
    }
    container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }, [messages.length, status]);

  const mergedItems = useMemo(() => {
    const remote = buildRemoteFeedItems([...entries].reverse());
    const local = buildLocalFeedMessages(messages, currentSessionId || activeSessionId);
    return [...remote, ...local].sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
  }, [entries, messages, currentSessionId, activeSessionId]);

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
            canAnchorChildRuns(block.anchorItem) &&
            block.anchorItem.sessionId === item.entry.parent_session_id,
        );
        if (parentBlockIndex >= 0) {
          currentBlocks[parentBlockIndex].childRuns.push(item);
          continue;
        }
      }
      currentBlocks.push({ anchorItem: item, childRuns: [] });
    }
    return groups;
  }, [mergedItems]);

  const searchMatches = useMemo(() => {
    const query = deferredSearch.trim().toLowerCase();
    if (!query) {
      return [];
    }
    return mergedItems.filter((item) => {
      if (item.kind === "message") {
        return item.message.content.toLowerCase().includes(query);
      }
      return entrySearchText(item.entry).includes(query);
    });
  }, [deferredSearch, mergedItems]);

  const matchedIds = useMemo(() => new Set(searchMatches.map((item) => item.id)), [searchMatches]);
  const activeSearchMatch = useMemo(
    () => searchMatches.findIndex((item) => item.id === activeSearchMatchId),
    [activeSearchMatchId, searchMatches],
  );
  const activeMatchId = activeSearchMatchId && searchMatches.some((item) => item.id === activeSearchMatchId)
    ? activeSearchMatchId
    : searchMatches.at(-1)?.id ?? null;

  useEffect(() => {
    if (!deferredSearch.trim()) {
      setActiveSearchMatchId(null);
      setPendingSearchDirection(null);
      return;
    }

    if (searchMatches.length === 0) {
      return;
    }

    const currentIndex = searchMatches.findIndex((item) => item.id === activeSearchMatchId);
    if (pendingSearchDirection === -1 && currentIndex > 0) {
      setActiveSearchMatchId(searchMatches[currentIndex - 1].id);
      setPendingSearchDirection(null);
      return;
    }

    if (currentIndex >= 0) {
      setPendingSearchDirection(null);
      return;
    }

    setActiveSearchMatchId(searchMatches.at(-1)?.id ?? null);
    setPendingSearchDirection(null);
  }, [deferredSearch, searchMatches, activeSearchMatchId, pendingSearchDirection]);

  useEffect(() => {
    if (!activeMatchId) {
      return;
    }
    const timeout = window.setTimeout(() => {
      const node = document.querySelector<HTMLElement>(`[data-stream-item-id="${activeMatchId}"]`);
      node?.scrollIntoView({ block: "center", behavior: "smooth" });
    }, 120);
    return () => window.clearTimeout(timeout);
  }, [activeMatchId]);

  const handleSessionJump = (sessionId: string | null) => {
    onSelectSession(sessionId);
    setFocusSessionId(sessionId);
  };

  const toggleExpanded = (entryId: string) => {
    setExpandedEntryIds((current) => ({
      ...current,
      [entryId]: !current[entryId],
    }));
  };

  const jumpToSearchMatch = (direction: 1 | -1) => {
    if (searchMatches.length === 0) {
      return;
    }
    const currentIndex = searchMatches.findIndex((item) => item.id === activeMatchId);
    const fallbackIndex = searchMatches.length - 1;
    const resolvedIndex = currentIndex >= 0 ? currentIndex : fallbackIndex;

    if (direction === -1 && resolvedIndex === 0 && total > entries.length) {
      setPendingSearchDirection(-1);
      setPage((value) => value + 1);
      return;
    }

    const nextIndex = resolvedIndex + direction;
    if (nextIndex < 0) {
      setActiveSearchMatchId(searchMatches.at(-1)?.id ?? null);
      return;
    }
    if (nextIndex >= searchMatches.length) {
      setActiveSearchMatchId(searchMatches[0]?.id ?? null);
      return;
    }
    setActiveSearchMatchId(searchMatches[nextIndex].id);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <div className="flex flex-wrap items-center gap-2">
          <SessionDropdown
            activeSessionId={activeSessionId}
            onSelectSession={handleSessionJump}
            onNewSession={onNewSession}
            projectId={PROJECT_ID}
            refreshTrigger={sidebarRefreshTrigger}
          />
          <div className="relative min-w-[18rem] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search Jenny's history, task IDs, files, agents..."
              className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-sm text-slate-700 outline-none transition focus:border-sky-300 focus:bg-white dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:border-sky-700"
            />
          </div>
          <TimeRangeDropdown value={timeRange} onChange={setTimeRange} />
        </div>
        {deferredSearch.trim() && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
            <span>
              {searchMatches.length === 0
                ? `No matches for "${deferredSearch.trim()}"`
                : `${Math.max(activeSearchMatch, 0) + 1} of ${searchMatches.length} loaded matches for "${deferredSearch.trim()}"${total > entries.length ? ` (${entries.length} of ${total} entries loaded)` : ""}`}
            </span>
            {searchMatches.length > 0 && (
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
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4">
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
            {groupedItems.map((group) => (
              <div key={group.label}>
                <DateDivider label={group.label} />
                <div className="space-y-3">
                  {group.blocks.map((block) => {
                    const item = block.anchorItem;
                    const selected = !!item.sessionId && item.sessionId === activeSessionId;
                    const matched = matchedIds.has(item.id);
                    const activeMatched = activeMatchId === item.id;
                    if (item.kind === "message") {
                      return (
                        <div
                          key={item.id}
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
                            {block.childRuns.length > 0 && (
                              <ChildRunStack
                                childRuns={block.childRuns}
                                activeSessionId={activeSessionId}
                                expandedEntryIds={expandedEntryIds}
                                onToggle={toggleExpanded}
                                matchedIds={matchedIds}
                                activeMatchId={activeMatchId}
                              />
                            )}
                          </div>
                        </div>
                      );
                    }
                    if (item.kind === "child_run") {
                      return (
                        <div
                          key={item.id}
                          data-session-anchor={item.sessionId}
                          data-testid="stream-item"
                          data-stream-item-id={item.id}
                          data-timestamp={item.timestamp.toISOString()}
                          className={cn(
                            "flex items-start gap-3 rounded-2xl",
                            matched && "px-2 py-1 ring-1 ring-amber-200 dark:ring-amber-800",
                            activeMatched && "ring-2 ring-amber-400 dark:ring-amber-500",
                          )}
                        >
                          <TimelineTimestamp timestamp={item.timestamp} />
                          <div className="min-w-0 flex-1">
                            <ChildRunCard
                              entry={item.entry}
                              selected={selected}
                              expanded={!!expandedEntryIds[item.id]}
                              onToggle={() => toggleExpanded(item.id)}
                            />
                          </div>
                        </div>
                      );
                    }
                    return (
                      <div
                        key={item.id}
                        data-session-anchor={item.sessionId}
                        data-testid="stream-item"
                        data-stream-item-id={item.id}
                        data-timestamp={item.timestamp.toISOString()}
                        className={cn(
                          "flex items-start gap-3 rounded-2xl",
                          matched && "px-2 py-1 ring-1 ring-amber-200 dark:ring-amber-800",
                          activeMatched && "ring-2 ring-amber-400 dark:ring-amber-500",
                        )}
                      >
                        <TimelineTimestamp timestamp={item.timestamp} />
                        <div className="min-w-0 flex-1">
                          <HeartbeatCard
                            entry={item.entry}
                            selected={selected}
                            expanded={!!expandedEntryIds[item.id]}
                            onToggle={() => toggleExpanded(item.id)}
                          />
                          {block.childRuns.length > 0 && (
                            <ChildRunStack
                              childRuns={block.childRuns}
                              activeSessionId={activeSessionId}
                              expandedEntryIds={expandedEntryIds}
                              onToggle={toggleExpanded}
                              matchedIds={matchedIds}
                              activeMatchId={activeMatchId}
                            />
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}

            {total > entries.length && (
              <div className="flex justify-center pt-6">
                <button
                  onClick={() => setPage((value) => value + 1)}
                  className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-600 transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  {deferredSearch.trim() ? "Load more matching entries" : "Load older entries"}
                </button>
              </div>
            )}
          </div>
        )}
      </div>

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
