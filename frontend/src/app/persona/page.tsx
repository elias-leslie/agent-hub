"use client";

import { useMemo, Suspense } from "react";
import { Loader2, Settings } from "lucide-react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";

import { ChatPanel } from "@/components/chat";
import { SessionDropdown } from "@/components/chat/session-dropdown";
import { useChatSession } from "../chat/hooks/useChatSession";
import { usePersona } from "./hooks/usePersona";

const PROJECT_ID = "persona-sandbox";

function PersonaContent() {
  const searchParams = useSearchParams();

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

            <SessionDropdown
              activeSessionId={activeSessionId}
              onSelectSession={handleSelectSession}
              onNewSession={handleNewSession}
              projectId={PROJECT_ID}
              refreshTrigger={sidebarRefreshTrigger}
            />
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

      {/* Chat Area */}
      <main className="flex-1 min-h-0">
        {persona ? (
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
