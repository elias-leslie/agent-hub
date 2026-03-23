"use client";

import { Suspense } from "react";
import {
  Loader2,
  Settings,
  AlertCircle,
  HeartPulse,
  PauseCircle,
  PlayCircle,
  Square,
} from "lucide-react";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";

import { cn } from "@/lib/utils";
import { useChatSession } from "../chat/hooks/useChatSession";
import { usePersona } from "./hooks/usePersona";
import { useHeartbeat } from "./hooks/useHeartbeat";
import { usePersonaRuntime } from "./hooks/usePersonaRuntime";
import { UnifiedPersonaWorkspace } from "./components/UnifiedPersonaWorkspace";
import { useToastActions } from "@/components/error/toast";
import { getPersonaDisplayName } from "./utils/displayName";

type RuntimeLabel = "Paused" | "Blocked" | "Waiting" | "Finalizing" | "Working" | "Auto-run off" | "Idle";

function formatRuntimeLabel(
  phase: string | undefined,
  executionState: "active" | "paused",
  autoRunDisabled: boolean,
): RuntimeLabel {
  if (executionState === "paused") return "Paused";
  if (autoRunDisabled) return "Auto-run off";
  if (!phase) return "Idle";
  if (phase === "error") return "Blocked";
  if (phase === "waiting_for_model") return "Waiting";
  if (phase === "finalizing") return "Finalizing";
  return "Working";
}

const STATUS_DOT: Record<RuntimeLabel, string> = {
  Working: "bg-emerald-400 shadow-[0_0_6px_theme(colors.emerald.400)]",
  Waiting: "bg-emerald-400 animate-pulse shadow-[0_0_6px_theme(colors.emerald.400)]",
  Finalizing: "bg-emerald-400 shadow-[0_0_6px_theme(colors.emerald.400)]",
  Paused: "bg-amber-400 shadow-[0_0_6px_theme(colors.amber.400)]",
  Blocked: "bg-rose-400 shadow-[0_0_6px_theme(colors.rose.400)]",
  "Auto-run off": "bg-slate-500",
  Idle: "bg-slate-500",
};

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
  const runtime = usePersonaRuntime(activeSessionId);
  const toast = useToastActions();

  const isHeartbeatRunning = heartbeatStatus?.running || isTriggering;
  const heartbeatTooltip = heartbeatStatus?.last_run
    ? `Last heartbeat ${formatDistanceToNow(new Date(heartbeatStatus.last_run), { addSuffix: true })}`
    : "Never run";
  const executionState = persona?.execution_state ?? "active";
  const personaName = getPersonaDisplayName(persona?.name);
  const personaPaused = executionState === "paused";
  const autoRunDisabled = (persona?.heartbeat_interval_minutes ?? 0) === 0;
  const runtimeLabel = formatRuntimeLabel(runtime.primarySession?.live_activity?.phase, executionState, autoRunDisabled);
  const isActive = runtimeLabel === "Working" || runtimeLabel === "Waiting" || runtimeLabel === "Finalizing";

  const liveSummary = runtime.primarySession?.live_activity?.summary
    || (isHeartbeatRunning ? `${personaName} is actively working` : null)
    || (personaPaused ? `${personaName} is paused` : null)
    || (heartbeatStatus?.last_run
      ? `Last heartbeat ${formatDistanceToNow(new Date(heartbeatStatus.last_run), { addSuffix: true })}`
      : "Ready");

  const handlePersonaPauseResume = async () => {
    if (personaPaused) {
      updatePersona({ execution_state: "active" });
      toast.success(`${personaName} resumed`);
      return;
    }
    updatePersona({ execution_state: "paused" });
    if (runtime.primarySession) {
      const cancelled = await runtime.stopCurrentStream();
      if (cancelled) {
        toast.success(`${personaName} paused and live stream stopped`);
        return;
      }
    }
    toast.success(`${personaName} paused`);
  };

  const handleStopCurrentStream = async () => {
    const result = await runtime.stopActiveWork();
    if (result.cancelled > 0) {
      toast.success(
        result.attempted > 1
          ? `Stopped ${result.cancelled} active ${personaName} sessions`
          : `Stopped active ${personaName} work`,
      );
      return;
    }
    toast.warning(
      "No active work was cancellable",
      `${personaName} may be idle or already between turns.`,
    );
  };

  const handleHeartbeatTrigger = async () => {
    const sessionId = await triggerHeartbeat();
    if (sessionId) {
      handleSelectSession(sessionId);
    }
  };

  if (personaLoading) {
    return (
      <div className="h-full flex items-center justify-center bg-slate-950">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-slate-950">
      {/* ── Compact status bar ── */}
      <header className="flex-shrink-0 border-b border-slate-800 bg-slate-900/80 backdrop-blur-lg z-20 relative">
        <div className="flex items-center gap-3 px-4 py-2.5">
          {/* Left: name + status */}
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            <span className={cn("h-2.5 w-2.5 rounded-full flex-shrink-0 transition-all", STATUS_DOT[runtimeLabel])} />
            <h1 className="text-sm font-semibold text-slate-100 flex-shrink-0">
              {persona?.name || "Persona"}
            </h1>
            <span className="text-xs text-slate-500 flex-shrink-0">{runtimeLabel}</span>
            <span className="mx-1 text-slate-700 flex-shrink-0">|</span>
            <p className="text-sm text-slate-400 truncate min-w-0">
              {liveSummary}
            </p>
          </div>

          {/* Right: context-sensitive actions */}
          <div className="flex items-center gap-1 flex-shrink-0">
            {/* Show stop when actively working */}
            {isActive && runtime.primarySession && (
              <button
                onClick={handleStopCurrentStream}
                disabled={runtime.stoppingSessionId !== null}
                className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-rose-300 transition-colors hover:bg-rose-950/40 disabled:opacity-50"
                title={`Stop ${personaName}`}
              >
                <Square className="h-3.5 w-3.5" />
                {runtime.stoppingSessionId ? "Stopping..." : "Stop"}
              </button>
            )}

            {/* Heartbeat trigger when idle */}
            {!isActive && !personaPaused && (
              <button
                onClick={handleHeartbeatTrigger}
                disabled={isHeartbeatRunning}
                aria-busy={isHeartbeatRunning}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors",
                  isHeartbeatRunning
                    ? "text-amber-400 cursor-not-allowed"
                    : "text-slate-300 hover:bg-slate-800",
                )}
                title={heartbeatTooltip}
              >
                <HeartPulse
                  className={cn("h-3.5 w-3.5", isHeartbeatRunning && "animate-pulse text-amber-400")}
                />
                {isHeartbeatRunning ? "Running..." : "Heartbeat"}
              </button>
            )}

            {/* Pause/Resume */}
            <button
              onClick={handlePersonaPauseResume}
              className={cn(
                "inline-flex items-center gap-1 rounded-lg p-1.5 transition-colors",
                personaPaused
                  ? "text-emerald-400 hover:bg-emerald-950/30"
                  : "text-slate-400 hover:bg-slate-800",
              )}
              title={personaPaused ? `Resume ${personaName}` : `Pause ${personaName}`}
            >
              {personaPaused ? <PlayCircle className="h-4 w-4" /> : <PauseCircle className="h-4 w-4" />}
            </button>

            {/* Settings */}
            <Link
              href={activeSessionId ? `/persona/settings?session_id=${activeSessionId}` : "/persona/settings"}
              className="p-1.5 rounded-lg transition-colors text-slate-400 hover:bg-slate-800 hover:text-slate-200"
              title="Settings"
            >
              <Settings className="h-4 w-4" />
            </Link>
          </div>
        </div>

        {runtime.error && (
          <div className="px-4 pb-2">
            <p className="text-xs text-rose-400">{runtime.error}</p>
          </div>
        )}
      </header>

      <main className="min-h-0 flex-1">
        {persona ? (
          <UnifiedPersonaWorkspace
            agentSlug={persona.agent_slug}
            personaName={personaName}
            activeSessionId={activeSessionId}
            sidebarRefreshTrigger={sidebarRefreshTrigger}
            runtimeSyncKey={runtime.runtimeSyncKey}
            onSelectSession={handleSelectSession}
            onSessionCreated={handleSessionCreated}
            onNewSession={handleNewSession}
          />
        ) : personaError ? (
          <div className="h-full flex flex-col items-center justify-center gap-2 text-rose-400">
            <AlertCircle className="h-6 w-6" />
            <p className="text-sm font-medium">Failed to load persona</p>
            <p className="text-xs text-rose-500 max-w-md text-center">{personaError}</p>
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
        <div className="h-full flex items-center justify-center bg-slate-950">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      }
    >
      <PersonaContent />
    </Suspense>
  );
}
