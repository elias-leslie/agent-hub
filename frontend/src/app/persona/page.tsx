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
  Terminal,
  Files,
  Bot,
  Square,
  MessageSquarePlus,
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

function formatRuntimeLabel(
  phase: string | undefined,
  executionState: "active" | "paused",
  autoRunDisabled: boolean,
): string {
  if (executionState === "paused") return "Paused";
  if (autoRunDisabled) return "Auto-run off";
  if (!phase) return "Idle";
  if (phase === "error") return "Blocked";
  if (phase === "waiting_for_model") return "Waiting";
  if (phase === "finalizing") return "Finalizing";
  return "Working";
}

function runtimeToneClasses(label: string): string {
  if (label === "Blocked") {
    return "bg-rose-50 text-rose-700 ring-1 ring-rose-200 dark:bg-rose-950/30 dark:text-rose-300 dark:ring-rose-800";
  }
  if (label === "Paused") {
    return "bg-amber-50 text-amber-700 ring-1 ring-amber-200 dark:bg-amber-950/30 dark:text-amber-300 dark:ring-amber-800";
  }
  if (label === "Auto-run off") {
    return "bg-slate-100 text-slate-700 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700";
  }
  if (label === "Working") {
    return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-800";
  }
  return "bg-slate-100 text-slate-700 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:ring-slate-700";
}

function PersonaContent() {
  const { persona, loading: personaLoading, error: personaError, updatePersona } = usePersona();
  const { status: heartbeatStatus, trigger: triggerHeartbeat, isTriggering } = useHeartbeat();
  const runtime = usePersonaRuntime();
  const toast = useToastActions();

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
  const executionState = persona?.execution_state ?? "active";
  const jennyPaused = executionState === "paused";
  const autoRunDisabled = (persona?.heartbeat_interval_minutes ?? 0) === 0;
  const heartbeatSummary = isHeartbeatRunning
    ? "Jenny is actively working"
    : jennyPaused
      ? "Jenny is paused"
      : autoRunDisabled
        ? "Auto-run is disabled"
      : heartbeatStatus?.last_run
        ? `Last heartbeat ${formatDistanceToNow(new Date(heartbeatStatus.last_run), {
            addSuffix: true,
          })}`
        : "No heartbeat has run yet";
  const runtimeLabel = formatRuntimeLabel(runtime.primarySession?.live_activity?.phase, executionState, autoRunDisabled);
  const activeChildCount = runtime.activeChildSessions.length;
  const liveSummary = runtime.primarySession?.live_activity?.summary || heartbeatSummary;
  const currentTool = runtime.primarySession?.live_activity?.current_tool_name
    || runtime.primarySession?.live_activity?.last_tool_name;
  const touchedFiles = runtime.primarySession?.live_activity?.files_touched?.slice(-3) || [];

  const handleJennyPauseResume = async () => {
    if (jennyPaused) {
      updatePersona({
        execution_state: "active",
      });
      toast.success("Jenny resumed");
      return;
    }

    updatePersona({
      execution_state: "paused",
    });

    if (runtime.primarySession) {
      const cancelled = await runtime.stopCurrentStream();
      if (cancelled) {
        toast.success("Jenny paused and live stream stopped");
        return;
      }
    }
    toast.success("Jenny paused");
  };

  const handleStopCurrentStream = async () => {
    const result = await runtime.stopActiveWork();
    if (result.cancelled > 0) {
      toast.success(
        result.attempted > 1
          ? `Stopped ${result.cancelled} active Jenny sessions`
          : "Stopped active Jenny work",
      );
      return;
    }
    toast.warning("No active work was cancellable", "Jenny may be idle or already between turns.");
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
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold",
                runtimeToneClasses(runtimeLabel),
              )}
            >
              <Activity className="h-3.5 w-3.5" />
              {runtimeLabel}
            </span>

            <button
              onClick={handleJennyPauseResume}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
                jennyPaused
                  ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 hover:bg-emerald-100 dark:bg-emerald-950/30 dark:text-emerald-300 dark:ring-emerald-800"
                  : "bg-amber-50 text-amber-700 ring-1 ring-amber-200 hover:bg-amber-100 dark:bg-amber-950/30 dark:text-amber-300 dark:ring-amber-800",
              )}
              title={jennyPaused ? "Resume Jenny" : "Pause Jenny and stop live work if active"}
            >
              {jennyPaused ? <PlayCircle className="h-3.5 w-3.5" /> : <PauseCircle className="h-3.5 w-3.5" />}
              {jennyPaused ? "Resume Jenny" : "Pause Jenny"}
            </button>

            <button
              onClick={triggerHeartbeat}
              disabled={isHeartbeatRunning || jennyPaused}
              aria-busy={isHeartbeatRunning}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all",
                isHeartbeatRunning || jennyPaused
                  ? "text-rose-500 dark:text-rose-400 cursor-not-allowed"
                  : "bg-sky-50 text-sky-700 ring-1 ring-sky-200 hover:bg-sky-100 dark:bg-sky-950/30 dark:text-sky-300 dark:ring-sky-800",
              )}
              title={jennyPaused ? "Resume Jenny to run a heartbeat" : heartbeatTooltip}
            >
              <HeartPulse
                className={cn(
                  "h-4 w-4",
                  isHeartbeatRunning && "animate-pulse text-rose-500 dark:text-rose-400",
                )}
              />
              {isHeartbeatRunning ? "Running..." : "Heartbeat"}
            </button>

            <button
              onClick={handleStopCurrentStream}
              disabled={!runtime.primarySession || runtime.stoppingSessionId !== null}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all",
                !runtime.primarySession || runtime.stoppingSessionId
                  ? "cursor-not-allowed bg-slate-100 text-slate-400 dark:bg-slate-900 dark:text-slate-600"
                  : "bg-rose-50 text-rose-700 ring-1 ring-rose-200 hover:bg-rose-100 dark:bg-rose-950/30 dark:text-rose-300 dark:ring-rose-800",
              )}
              title="Best-effort stop for Jenny and any active spawned work"
            >
              <Square className="h-3.5 w-3.5" />
              {runtime.stoppingSessionId ? "Stopping..." : "Stop active work"}
            </button>

            <button
              onClick={handleNewSession}
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
              title="Start a new Jenny thread"
            >
              <MessageSquarePlus className="h-3.5 w-3.5" />
              New thread
            </button>
          </div>

          <div className="grid gap-2 text-xs text-slate-600 dark:text-slate-300 md:grid-cols-[minmax(0,2fr)_repeat(3,minmax(0,1fr))]">
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
              <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">
                Jenny Is Doing
              </div>
              <div className="mt-1 text-sm font-medium text-slate-800 dark:text-slate-100">
                {liveSummary}
              </div>
              {runtime.primarySession?.updated_at && (
                <div className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                  Updated {formatDistanceToNow(new Date(runtime.primarySession.updated_at), { addSuffix: true })}
                </div>
              )}
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
              <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">
                Current Tool
              </div>
              <div className="mt-1 inline-flex items-center gap-1.5 text-sm font-medium text-slate-800 dark:text-slate-100">
                <Terminal className="h-3.5 w-3.5 text-slate-400" />
                {currentTool || "Idle"}
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
              <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">
                Spawned Agents
              </div>
              <div className="mt-1 inline-flex items-center gap-1.5 text-sm font-medium text-slate-800 dark:text-slate-100">
                <Bot className="h-3.5 w-3.5 text-slate-400" />
                {activeChildCount} active
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
              <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">
                Files Touched
              </div>
              <div className="mt-1 inline-flex items-center gap-1.5 text-sm font-medium text-slate-800 dark:text-slate-100">
                <Files className="h-3.5 w-3.5 text-slate-400" />
                {touchedFiles.length > 0 ? touchedFiles.join(", ") : "None yet"}
              </div>
            </div>
          </div>

          {runtime.error && (
            <p className="text-xs text-rose-500 dark:text-rose-400">{runtime.error}</p>
          )}
        </div>
      </header>

      <main className="min-h-0 flex-1">
        {persona ? (
          <UnifiedPersonaWorkspace
            agentSlug={persona.agent_slug}
            activeSessionId={activeSessionId}
            sidebarRefreshTrigger={sidebarRefreshTrigger}
            runtimeSyncKey={runtime.runtimeSyncKey}
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
