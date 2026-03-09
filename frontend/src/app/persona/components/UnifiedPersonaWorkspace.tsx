"use client";

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

type FeedItem =
  | { kind: "message"; id: string; sessionId: string | null; timestamp: Date; message: ChatMessage }
  | {
      kind: "heartbeat" | "child_run";
      id: string;
      sessionId: string;
      timestamp: Date;
      entry: PersonaStreamEntry;
    };

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

function ChildRunCard({ entry, selected }: { entry: PersonaStreamEntry; selected: boolean }) {
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
          </div>
        </div>
      </div>
    </div>
  );
}

function HeartbeatCard({ entry, selected }: { entry: PersonaStreamEntry; selected: boolean }) {
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
    const groups: Array<{ label: string; items: FeedItem[] }> = [];
    let currentLabel = "";
    for (const item of mergedItems) {
      const label = formatDayLabel(item.timestamp);
      if (label !== currentLabel) {
        currentLabel = label;
        groups.push({ label, items: [] });
      }
      groups[groups.length - 1].items.push(item);
    }
    return groups;
  }, [mergedItems]);

  const handleSessionJump = (sessionId: string | null) => {
    onSelectSession(sessionId);
    setFocusSessionId(sessionId);
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
                  {group.items.map((item) => {
                    const selected = !!item.sessionId && item.sessionId === activeSessionId;
                    if (item.kind === "message") {
                      return (
                        <div
                          key={item.id}
                          data-session-anchor={item.sessionId ?? undefined}
                          className={cn(selected && "rounded-2xl bg-sky-50/40 px-2 py-1 dark:bg-sky-950/10")}
                        >
                          <MessageBubble
                            message={item.message}
                            isStreaming={status !== "idle" && status !== "error"}
                            canEdit={false}
                            canRegenerate={false}
                          />
                        </div>
                      );
                    }
                    if (item.kind === "child_run") {
                      return (
                        <div key={item.id} data-session-anchor={item.sessionId}>
                          <ChildRunCard entry={item.entry} selected={selected} />
                        </div>
                      );
                    }
                    return (
                      <div key={item.id} data-session-anchor={item.sessionId}>
                        <HeartbeatCard entry={item.entry} selected={selected} />
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
                  Load older entries
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
