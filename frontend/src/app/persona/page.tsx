"use client";

import { useMemo, Suspense } from "react";
import {
  Loader2,
  Settings,
  MessageSquare,
  AlertCircle,
  HeartPulse,
  PauseCircle,
  PlayCircle,
  Plus,
  Activity,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";

import { ChatPanel } from "@/components/chat";
import { SessionDropdown } from "@/components/chat/session-dropdown";
import { cn } from "@/lib/utils";
import { useChatSession } from "../chat/hooks/useChatSession";
import { usePersona } from "./hooks/usePersona";
import { useHeartbeat } from "./hooks/useHeartbeat";
import { ActivityTimeline } from "./components/ActivityTimeline";

const PROJECT_ID = "persona-sandbox";

function PersonaContent() {
  const searchParams = useSearchParams();
  const { persona, loading: personaLoading, error: personaError, updatePersona } = usePersona();
  const { status: heartbeatStatus, trigger: triggerHeartbeat, isTriggering } = useHeartbeat();

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

  const isHeartbeatRunning = heartbeatStatus?.running || isTriggering;
  const heartbeatTooltip = heartbeatStatus?.last_run
    ? `Last: ${formatDistanceToNow(new Date(heartbeatStatus.last_run), { addSuffix: true })}`
    : "Never run";
  const autoRunPaused = (persona?.heartbeat_interval_minutes ?? 0) === 0;
  const heartbeatSummary = isHeartbeatRunning
    ? "Jenny is actively working"
    : autoRunPaused
      ? "Auto-run is paused"
      : heartbeatStatus?.last_run
        ? `Last heartbeat ${formatDistanceToNow(new Date(heartbeatStatus.last_run), {
            addSuffix: true,
          })}`
        : "No heartbeat has run yet";

  const handleAutoRunToggle = () => {
    updatePersona({
      heartbeat_interval_minutes: autoRunPaused ? 60 : 0,
    });
  };

  if (personaLoading) {
    return (
      <div className="h-full flex items-center justify-center bg-slate-50 dark:bg-slate-950">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-slate-50 dark:bg-slate-950">
      <header className="flex-shrink-0 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg z-20 relative">
        <div className="flex flex-col gap-3 px-4 py-3">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                  {persona?.name || "Persona"}
                </h1>
                <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  <Activity className="h-3 w-3" />
                  Unified workspace
                </span>
              </div>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {heartbeatSummary}
              </p>
            </div>

            <div className="flex items-center gap-1">
              <Link
                href={activeSessionId ? `/persona/settings?session_id=${activeSessionId}` : "/persona/settings"}
                className="p-2 rounded-lg transition-colors text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
                title="Persona settings"
              >
                <Settings className="h-5 w-5" />
              </Link>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <SessionDropdown
              activeSessionId={activeSessionId}
              onSelectSession={handleSelectSession}
              onNewSession={handleNewSession}
              projectId={PROJECT_ID}
              refreshTrigger={sidebarRefreshTrigger}
            />

            <button
              onClick={handleNewSession}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
                "bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50",
                "dark:bg-slate-900 dark:text-slate-200 dark:ring-slate-700 dark:hover:bg-slate-800",
              )}
            >
              <Plus className="h-3.5 w-3.5" />
              New chat
            </button>

            <button
              onClick={handleAutoRunToggle}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
                autoRunPaused
                  ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 hover:bg-emerald-100 dark:bg-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-800"
                  : "bg-amber-50 text-amber-700 ring-1 ring-amber-200 hover:bg-amber-100 dark:bg-amber-950/30 dark:text-amber-300 dark:ring-amber-800",
              )}
              title={autoRunPaused ? "Resume scheduled heartbeats" : "Pause scheduled heartbeats"}
            >
              {autoRunPaused ? <PlayCircle className="h-3.5 w-3.5" /> : <PauseCircle className="h-3.5 w-3.5" />}
              {autoRunPaused ? "Resume auto-run" : "Pause auto-run"}
            </button>

            <button
              onClick={triggerHeartbeat}
              disabled={isHeartbeatRunning}
              aria-busy={isHeartbeatRunning}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all",
                isHeartbeatRunning
                  ? "text-rose-500 dark:text-rose-400 cursor-not-allowed"
                  : "bg-sky-50 text-sky-700 ring-1 ring-sky-200 hover:bg-sky-100 dark:bg-sky-950/30 dark:text-sky-300 dark:ring-sky-800",
              )}
              title={heartbeatTooltip}
            >
              <HeartPulse
                className={cn(
                  "h-4 w-4",
                  isHeartbeatRunning && "animate-pulse text-rose-500 dark:text-rose-400",
                )}
              />
              {isHeartbeatRunning ? "Running..." : "Heartbeat"}
            </button>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1">
        {persona ? (
          <div className="grid h-full min-h-0 grid-cols-1 gap-4 p-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(24rem,0.9fr)]">
            <section className="min-h-[28rem] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-800">
                <div className="flex items-center gap-2">
                  <MessageSquare className="h-4 w-4 text-sky-500" />
                  <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                    Chat with {persona.name || "Jenny"}
                  </h2>
                </div>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  Use the composer below to interrupt, steer, or ask for status while work is in progress.
                </p>
              </div>
              <div className="h-[calc(100%-4.25rem)]">
                <ChatPanel
                  agentSlug={persona.agent_slug}
                  sessionId={activeSessionId || undefined}
                  toolsEnabled={true}
                  onSessionCreated={handleSessionCreated}
                  onClear={handleNewSession}
                  initialPrompt={initialPrompt}
                  projectId={PROJECT_ID}
                />
              </div>
            </section>

            <aside className="min-h-[28rem] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
              <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-800">
                <div className="flex items-center gap-2">
                  <HeartPulse className="h-4 w-4 text-amber-500" />
                  <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                    Activity inline
                  </h2>
                </div>
                <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  Heartbeats, autonomous runs, and chat sessions stay visible here without leaving the conversation.
                </p>
              </div>
              <ActivityTimeline
                onSelectChatSession={handleSelectSession}
                heartbeatRunning={isHeartbeatRunning}
                heartbeatLastRun={heartbeatStatus?.last_run ?? null}
              />
            </aside>
          </div>
        ) : personaError ? (
          <div className="h-full flex flex-col items-center justify-center gap-2 text-rose-500 dark:text-rose-400">
            <AlertCircle className="h-6 w-6" />
            <p className="text-sm font-medium">Failed to load persona</p>
            <p className="text-xs text-rose-400 dark:text-rose-500 max-w-md text-center">{personaError}</p>
          </div>
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
