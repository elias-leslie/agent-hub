"use client";

import { Suspense } from "react";
import {
  Loader2,
  Settings,
  AlertCircle,
  HeartPulse,
  PauseCircle,
  PlayCircle,
  Activity,
} from "lucide-react";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";

import { cn } from "@/lib/utils";
import { useChatSession } from "../chat/hooks/useChatSession";
import { usePersona } from "./hooks/usePersona";
import { useHeartbeat } from "./hooks/useHeartbeat";
import { UnifiedPersonaWorkspace } from "./components/UnifiedPersonaWorkspace";

function PersonaContent() {
  const { persona, loading: personaLoading, error: personaError, updatePersona } = usePersona();
  const { status: heartbeatStatus, trigger: triggerHeartbeat, isTriggering } = useHeartbeat();

  const {
    activeSessionId,
    sidebarRefreshTrigger,
    handleSessionCreated,
    handleSelectSession,
    handleNewSession,
  } = useChatSession();

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
          <UnifiedPersonaWorkspace
            agentSlug={persona.agent_slug}
            activeSessionId={activeSessionId}
            sidebarRefreshTrigger={sidebarRefreshTrigger}
            onSelectSession={handleSelectSession}
            onSessionCreated={handleSessionCreated}
            onNewSession={handleNewSession}
          />
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
