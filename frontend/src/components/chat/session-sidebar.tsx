"use client";

import { useState, useEffect, useCallback } from "react";
import {
  MessageSquare,
  Plus,
  Clock,
  ChevronRight,
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
  purpose: string | null;
  session_type: string;
  message_count: number;
  total_input_tokens: number;
  total_output_tokens: number;
  created_at: string;
  updated_at: string;
}

interface SessionSidebarProps {
  activeSessionId: string | null;
  onSelectSession: (sessionId: string | null) => void;
  onNewSession: () => void;
  projectId?: string;
  className?: string;
}

export function SessionSidebar({
  activeSessionId,
  onSelectSession,
  onNewSession,
  projectId = "agent-hub",
  className,
}: SessionSidebarProps) {
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSessions = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const url = new URL(`${getApiBaseUrl()}/api/sessions`);
      url.searchParams.set("page_size", "20");
      url.searchParams.set("session_type", "chat");
      if (projectId) {
        url.searchParams.set("project_id", projectId);
      }

      const res = await fetchApi(url.toString());
      if (!res.ok) {
        throw new Error(`Failed to fetch sessions: ${res.status}`);
      }
      const data = await res.json();
      setSessions(data.sessions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sessions");
    } finally {
      setIsLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const handleDeleteSession = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    try {
      await fetchApi(`${getApiBaseUrl()}/api/sessions/${sessionId}`, {
        method: "DELETE",
      });
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      if (activeSessionId === sessionId) {
        onSelectSession(null);
      }
    } catch {
      // Silent failure - user can refresh
    }
  };

  const getSessionTitle = (session: SessionItem): string => {
    if (session.purpose) return session.purpose;
    const modelName = session.model.split("-").slice(-2).join(" ");
    return `${modelName} chat`;
  };

  return (
    <div className={cn("flex flex-col h-full bg-slate-50 dark:bg-slate-900", className)}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-slate-200 dark:border-slate-800">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-300">
          Sessions
        </h2>
        <button
          onClick={onNewSession}
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
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
          </div>
        ) : error ? (
          <div className="px-3 py-4 text-sm text-red-500 dark:text-red-400">
            {error}
          </div>
        ) : sessions.length === 0 ? (
          <div className="px-3 py-8 text-center text-sm text-slate-500 dark:text-slate-400">
            <MessageSquare className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p>No sessions yet</p>
            <p className="text-xs mt-1">Start a new conversation</p>
          </div>
        ) : (
          <div className="py-1">
            {sessions.map((session) => (
              <button
                key={session.id}
                onClick={() => onSelectSession(session.id)}
                className={cn(
                  "w-full flex items-start gap-2 px-3 py-2 text-left transition-colors group",
                  activeSessionId === session.id
                    ? "bg-indigo-50 dark:bg-indigo-950/30 border-l-2 border-indigo-500"
                    : "hover:bg-slate-100 dark:hover:bg-slate-800 border-l-2 border-transparent"
                )}
              >
                <MessageSquare className="h-4 w-4 mt-0.5 flex-shrink-0 text-slate-400" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-300 truncate">
                      {getSessionTitle(session)}
                    </span>
                    {session.status === "active" && (
                      <ChevronRight className="h-3 w-3 text-indigo-500" />
                    )}
                  </div>
                  <div className="flex items-center gap-2 mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {formatDistanceToNow(new Date(session.updated_at), { addSuffix: true })}
                    </span>
                    {session.message_count > 0 && (
                      <span>{session.message_count} msgs</span>
                    )}
                  </div>
                </div>
                <button
                  onClick={(e) => handleDeleteSession(e, session.id)}
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
  );
}
