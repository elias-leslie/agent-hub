"use client";

import { useState, useMemo, useCallback, Suspense } from "react";
import { Loader2, Settings, MessageSquare, Radio } from "lucide-react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";

import { ChatPanel } from "@/components/chat";
import { SessionDropdown } from "@/components/chat/session-dropdown";
import { cn } from "@/lib/utils";
import { useChatSession } from "../chat/hooks/useChatSession";
import { usePersona } from "./hooks/usePersona";
import { ActivityTimeline } from "./components/ActivityTimeline";

const PROJECT_ID = "persona-sandbox";

type ViewMode = "chat" | "activity";

function PersonaContent() {
  const searchParams = useSearchParams();
  const [viewMode, setViewMode] = useState<ViewMode>("chat");

  const { persona, loading: personaLoading } = usePersona();

  const {
    activeSessionId,
    sidebarRefreshTrigger,
    handleSessionCreated,
    handleSelectSession,
    handleNewSession,
  } = useChatSession();

  // Deep-link support: ?prompt= and ?task= URL params
  const initialPrompt = useMemo(() => {
    const prompt = searchParams.get("prompt");
    const taskId = searchParams.get("task");
    if (prompt) return prompt;
    if (taskId) return `What's the status of task ${taskId}? What happened and what are my options?`;
    return undefined;
  }, [searchParams]);

  const handleSelectChatSession = useCallback(
    (sessionId: string) => {
      handleSelectSession(sessionId);
      setViewMode("chat");
    },
    [handleSelectSession],
  );

  if (personaLoading) {
    return (
      <div className="h-full flex items-center justify-center bg-slate-50 dark:bg-slate-950">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-slate-50 dark:bg-slate-950">
      {/* Header */}
      <header className="flex-shrink-0 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg z-20 relative">
        <div className="flex items-center justify-between px-4 h-14">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {persona?.name || "Persona"}
            </h1>

            {/* View mode toggle */}
            <div className="flex items-center rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-100/80 dark:bg-slate-800/80 p-0.5">
              <button
                onClick={() => setViewMode("chat")}
                className={cn(
                  "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-all",
                  viewMode === "chat"
                    ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-sm"
                    : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200",
                )}
              >
                <MessageSquare className="w-3 h-3" />
                Chat
              </button>
              <button
                onClick={() => setViewMode("activity")}
                className={cn(
                  "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-all",
                  viewMode === "activity"
                    ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-sm"
                    : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200",
                )}
              >
                <Radio className="w-3 h-3" />
                Activity
              </button>
            </div>

            {viewMode === "chat" && (
              <SessionDropdown
                activeSessionId={activeSessionId}
                onSelectSession={handleSelectSession}
                onNewSession={handleNewSession}
                projectId={PROJECT_ID}
                refreshTrigger={sidebarRefreshTrigger}
              />
            )}
          </div>

          {/* Settings Gear */}
          <Link
            href={activeSessionId ? `/persona/settings?session_id=${activeSessionId}` : "/persona/settings"}
            className="p-2 rounded-lg transition-colors text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
            title="Persona settings"
          >
            <Settings className="h-5 w-5" />
          </Link>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 min-h-0">
        {viewMode === "chat" ? (
          persona ? (
            <ChatPanel
              agentSlug={persona.agent_slug}
              sessionId={activeSessionId || undefined}
              toolsEnabled={true}
              onSessionCreated={handleSessionCreated}
              onClear={handleNewSession}
              initialPrompt={initialPrompt}
              projectId={PROJECT_ID}
            />
          ) : (
            <div className="h-full flex items-center justify-center text-slate-500">
              Persona not configured
            </div>
          )
        ) : (
          <ActivityTimeline onSelectChatSession={handleSelectChatSession} />
        )}
      </main>
    </div>
  );
}

export default function PersonaPage() {
  return (
    <Suspense
      fallback={
        <div className="h-full flex items-center justify-center bg-slate-50 dark:bg-slate-950">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      }
    >
      <PersonaContent />
    </Suspense>
  );
}
