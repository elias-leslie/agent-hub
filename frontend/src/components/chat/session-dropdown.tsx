"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  MessageSquare,
  Plus,
  Clock,
  ChevronDown,
  Trash2,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getApiBaseUrl, fetchApi } from "@/lib/api-config";
import { formatDistanceToNow } from "date-fns";

interface SessionItem {
  id: string;
  project_id: string;
  provider: string;
  model: string;
  status: string;
  agent_slug: string | null;
  session_type: string;
  external_id?: string | null;
  current_branch?: string | null;
  summary_oneliner?: string | null;
  message_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  created_at: string;
  updated_at: string;
}

interface SessionDropdownProps {
  activeSessionId: string | null;
  onSelectSession: (sessionId: string | null) => void;
  onNewSession: () => void;
  projectId?: string;
  agentSlug?: string;
  /** Increment to trigger a refresh of the session list */
  refreshTrigger?: number;
}

export function SessionDropdown({
  activeSessionId,
  onSelectSession,
  onNewSession,
  projectId = "agent-hub",
  agentSlug,
  refreshTrigger = 0,
}: SessionDropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasFetched, setHasFetched] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const fetchSessions = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("page_size", "30");
      if (projectId) {
        params.set("project_id", projectId);
      }
      if (agentSlug) {
        params.set("agent_slug", agentSlug);
      }

      const res = await fetchApi(
        `${getApiBaseUrl()}/api/sessions?${params.toString()}`
      );
      if (!res.ok) {
        throw new Error(`Failed to fetch sessions: ${res.status}`);
      }
      const data = await res.json();
      setSessions(data.sessions || []);
      setHasFetched(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sessions");
    } finally {
      setIsLoading(false);
    }
  }, [projectId]);

  // Lazy fetch: load sessions when dropdown opens
  useEffect(() => {
    if (isOpen) {
      fetchSessions();
    }
  }, [isOpen, fetchSessions]);

  // Re-fetch when refreshTrigger changes while open
  useEffect(() => {
    if (isOpen && hasFetched && refreshTrigger > 0) {
      fetchSessions();
    }
  }, [refreshTrigger]); // eslint-disable-line react-hooks/exhaustive-deps

  // Click-outside dismissal
  useEffect(() => {
    function handleMouseDown(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, []);

  // Escape key dismissal
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && isOpen) {
        setIsOpen(false);
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  const handleDeleteSession = async (
    e: React.MouseEvent,
    sessionId: string
  ) => {
    e.stopPropagation();
    try {
      await fetchApi(`${getApiBaseUrl()}/api/sessions/${sessionId}`, {
        method: "DELETE",
      });
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      if (activeSessionId === sessionId) {
        onSelectSession(null);
      }
    } catch (err) {
      console.error("Failed to delete session", sessionId, err);
    }
  };

  const getSessionTitle = (session: SessionItem): string => {
    if (session.summary_oneliner) return session.summary_oneliner;
    if (session.external_id) return `${session.external_id} • ${session.session_type}`;
    if (session.current_branch) return session.current_branch;
    if (session.agent_slug) return `${session.agent_slug} • ${session.session_type}`;
    const modelName = session.model.split("-").slice(-2).join(" ");
    return `${modelName} ${session.session_type}`;
  };

  const getSessionMeta = (session: SessionItem): string[] => {
    const parts: string[] = [];
    parts.push(session.session_type);
    if (session.external_id) {
      parts.push(session.external_id);
    }
    if (session.project_id && session.project_id !== "persona-sandbox") {
      parts.push(session.project_id);
    }
    return parts;
  };

  const handleSelectSession = (sessionId: string) => {
    onSelectSession(sessionId);
    setIsOpen(false);
  };

  const handleNewSession = () => {
    onNewSession();
    setIsOpen(false);
  };

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Trigger Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium",
          "bg-indigo-900/20 text-indigo-400",
          "hover:bg-indigo-900/40 transition-colors"
        )}
      >
        <MessageSquare className="h-3.5 w-3.5" />
        Sessions
        <ChevronDown
          className={cn(
            "h-3 w-3 transition-transform",
            isOpen && "rotate-180"
          )}
        />
      </button>

      {/* Dropdown Panel */}
      {isOpen && (
        <div className="absolute left-0 top-full mt-1 w-72 rounded-lg border border-slate-700 bg-slate-800 shadow-lg z-50">
          {/* Header */}
          <div className="flex items-center justify-between px-3 py-2.5 border-b border-slate-700">
            <span className="text-sm font-semibold text-slate-300">
              Sessions
            </span>
            <button
              onClick={handleNewSession}
              className={cn(
                "flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium",
                "bg-indigo-500 text-white hover:bg-indigo-600 transition-colors"
              )}
            >
              <Plus className="h-3.5 w-3.5" />
              New
            </button>
          </div>

          {/* Session List */}
          <div className="max-h-80 overflow-y-auto">
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
              </div>
            ) : error ? (
              <div className="px-3 py-4 text-sm text-red-400">
                {error}
              </div>
            ) : sessions.length === 0 ? (
              <div className="px-3 py-8 text-center text-sm text-slate-400">
                <MessageSquare className="h-8 w-8 mx-auto mb-2 opacity-50" />
                <p>No sessions yet</p>
                <p className="text-xs mt-1">Start a new conversation</p>
              </div>
            ) : (
              <div className="py-1">
                {sessions.map((session) => (
                  <button
                    key={session.id}
                    onClick={() => handleSelectSession(session.id)}
                    className={cn(
                      "w-full flex items-start gap-2 px-3 py-2 text-left transition-colors group",
                      activeSessionId === session.id
                        ? "bg-indigo-50 dark:bg-indigo-950/30"
                        : "hover:bg-slate-700/50"
                    )}
                  >
                    <MessageSquare className="h-4 w-4 mt-0.5 flex-shrink-0 text-slate-400" />
                    <div className="flex-1 min-w-0">
                      <span className="text-sm font-medium text-slate-300 truncate block">
                        {getSessionTitle(session)}
                      </span>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {getSessionMeta(session).map((meta) => (
                          <span
                            key={`${session.id}-${meta}`}
                            className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500 bg-slate-700 dark:text-slate-300"
                          >
                            {meta}
                          </span>
                        ))}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5 text-xs text-slate-400">
                        <span className="flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {formatDistanceToNow(new Date(session.updated_at), {
                            addSuffix: true,
                          })}
                        </span>
                        {session.message_count > 0 && (
                          <span>{session.message_count} msgs</span>
                        )}
                      </div>
                    </div>
                    <button
                      onClick={(e) => handleDeleteSession(e, session.id)}
                      aria-label="Delete session"
                      className={cn(
                        "p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity",
                        "text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
                      )}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
