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
import type { HeartbeatStatusResponse } from "@/lib/api/dashboard";
import { useChatSession } from "../chat/hooks/useChatSession";
import { usePersona } from "./hooks/usePersona";
import { useHeartbeat } from "./hooks/useHeartbeat";
import { usePersonaRuntime } from "./hooks/usePersonaRuntime";
import { UnifiedPersonaWorkspace } from "./components/UnifiedPersonaWorkspace";
import { useToastActions } from "@/components/error/toast";
import { getPersonaDisplayName } from "./utils/displayName";
import { prettifyDisplayText, shortenText } from "./components/workspace-format";

type RuntimeLabel = "Paused" | "Blocked" | "Waiting" | "Finalizing" | "Working" | "Auto-run off" | "Ready";

type SummaryDescriptor = {
  text: string;
  source: "runtime" | "session" | "advisory";
};

function formatRuntimeLabel(
  phase: string | undefined,
  executionState: "active" | "paused",
  autoRunDisabled: boolean,
): RuntimeLabel {
  if (executionState === "paused") return "Paused";
  if (autoRunDisabled) return "Auto-run off";
  if (!phase) return "Ready";
  if (phase === "error") return "Blocked";
  if (phase === "waiting_for_model") return "Waiting";
  if (phase === "finalizing") return "Finalizing";
  return "Working";
}

function formatHeartbeatFallbackSummary(status: HeartbeatStatusResponse | null | undefined): string | null {
  if (!status?.running) {
    return null;
  }
  const scope = status.running_project_id ? ` for ${status.running_project_id}` : "";
  const trigger = status.running_trigger === "manual_api"
    ? " via manual trigger"
    : status.running_trigger === "cron"
      ? " via schedule"
      : status.running_trigger === "manual"
        ? " via manual run"
        : "";
  return `Check running${scope}${trigger}`;
}

function buildLiveSummaryDescriptor(args: {
  runtimeSummary: string | null | undefined;
  heartbeatStatus: HeartbeatStatusResponse | null | undefined;
  isHeartbeatRunning: boolean;
  personaPaused: boolean;
  personaName: string;
}): SummaryDescriptor {
  if (args.runtimeSummary) {
    return {
      text: shortenText(prettifyDisplayText(args.runtimeSummary) || args.runtimeSummary, 180),
      source: "runtime",
    };
  }
  const heartbeatFallback = formatHeartbeatFallbackSummary(args.heartbeatStatus);
  if (heartbeatFallback) {
    return { text: heartbeatFallback, source: "advisory" };
  }
  if (args.isHeartbeatRunning) {
    return { text: "Check running", source: "advisory" };
  }
  if (args.personaPaused) {
    return { text: `${args.personaName} is paused`, source: "session" };
  }
  if (args.heartbeatStatus?.last_run) {
    return {
      text: `Last check-in ${formatDistanceToNow(new Date(args.heartbeatStatus.last_run), { addSuffix: true })}`,
      source: "advisory",
    };
  }
  return { text: "", source: "session" };
}

function isChildLaneActive(
  session: { status?: string; live_activity?: { status?: string } | null } | null | undefined,
): boolean {
  return Boolean(
    session
    && (session.status === "active" || session.live_activity?.status === "active"),
  );
}

const STATUS_DOT: Record<RuntimeLabel, string> = {
  Working: "bg-emerald-400",
  Waiting: "bg-emerald-400",
  Finalizing: "bg-emerald-400",
  Paused: "bg-amber-400",
  Blocked: "bg-rose-400",
  "Auto-run off": "bg-slate-500",
  Ready: "bg-slate-500",
};

function PersonaContent() {
  const { persona, loading: personaLoading, error: personaError, updatePersona, autosave } = usePersona();
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
    ? `Last check-in ${formatDistanceToNow(new Date(heartbeatStatus.last_run), { addSuffix: true })}`
    : "No check-ins yet";
  const executionState = persona?.execution_state ?? "active";
  const personaName = getPersonaDisplayName(persona?.name);
  const personaPaused = executionState === "paused";
  const autoRunDisabled = (persona?.heartbeat_interval_minutes ?? 0) === 0;
  const runtimeLabel = formatRuntimeLabel(runtime.primarySession?.live_activity?.phase, executionState, autoRunDisabled);
  const isActive = runtimeLabel === "Working" || runtimeLabel === "Waiting" || runtimeLabel === "Finalizing";
  const activeWorkCount = Number(Boolean(runtime.primarySession)) + Number(runtime.activeChildSessions.some(isChildLaneActive));
  const liveSummary = buildLiveSummaryDescriptor({
    runtimeSummary: runtime.primarySession?.live_activity?.summary,
    heartbeatStatus,
    isHeartbeatRunning,
    personaPaused,
    personaName,
  });

  const handlePersonaPauseResume = async () => {
    await updatePersona({ execution_state: personaPaused ? "active" : "paused" });
    if (!personaPaused && runtime.primarySession) {
      await runtime.stopCurrentStream();
    }
  };

  const handleStopCurrentStream = async () => {
    if (!runtime.primarySession) {
      toast.warning(
        "No active session to stop",
        `${personaName} has no focused persisted session running right now.`,
      );
      return;
    }
    const cancelled = await runtime.stopCurrentStream();
    if (cancelled) {
      toast.success(`Stopped live work for ${personaName}`);
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
        <Loader2 className="h-6 w-6 animate-spin text-amber-500/50" />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden bg-slate-950">
      <header className="sticky top-0 z-30 flex-shrink-0 border-b border-slate-800/60 bg-slate-950/95 backdrop-blur-xl">
        <div className="flex flex-col gap-3 px-5 py-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className={cn("block h-2 w-2 rounded-full transition-all", STATUS_DOT[runtimeLabel])} />
              <h1 className="text-sm font-semibold tracking-wide text-slate-50">{personaName}</h1>
              <span className={cn(
                "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.18em]",
                isActive ? "bg-emerald-500/12 text-emerald-300" :
                personaPaused ? "bg-amber-500/12 text-amber-300" :
                runtimeLabel === "Blocked" ? "bg-rose-500/12 text-rose-300" :
                "bg-slate-900 text-slate-500",
              )}>
                {runtimeLabel}
              </span>
              {autosave.status === "saving" || autosave.status === "scheduled" ? (
                <span className="text-xs text-slate-500">saving…</span>
              ) : null}
              {autosave.status === "error" ? (
                <span className="text-xs text-rose-300">save failed</span>
              ) : null}
            </div>
            {liveSummary.text ? (
              <p className="mt-1 truncate text-sm text-slate-400">{liveSummary.text}</p>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-2 xl:justify-end">
            <button
              onClick={handleHeartbeatTrigger}
              disabled={personaPaused || isHeartbeatRunning}
              aria-busy={isHeartbeatRunning}
              className={cn(
                "inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-all",
                personaPaused || isHeartbeatRunning
                  ? "cursor-not-allowed border-slate-800 bg-slate-900/70 text-slate-500"
                  : "border-slate-800 bg-slate-950/80 text-slate-200 hover:border-slate-700 hover:bg-slate-900",
              )}
              title={heartbeatTooltip}
            >
              <HeartPulse className={cn("h-3.5 w-3.5", isHeartbeatRunning && "animate-pulse text-amber-300")} />
              {isHeartbeatRunning ? "Check running" : "Check now"}
            </button>

            <button
              onClick={handleStopCurrentStream}
              disabled={activeWorkCount === 0 || runtime.stoppingSessionId !== null}
              className="inline-flex items-center gap-2 rounded-lg border border-rose-500/20 bg-rose-950/15 px-3 py-2 text-xs font-medium text-rose-200 transition-all hover:border-rose-500/40 hover:bg-rose-950/25 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Square className="h-3.5 w-3.5" />
              {runtime.stoppingSessionId ? "Stopping…" : "Stop"}
            </button>

            <button
              onClick={handlePersonaPauseResume}
              className={cn(
                "inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-all",
                personaPaused
                  ? "border-emerald-500/20 bg-emerald-950/15 text-emerald-200 hover:border-emerald-400/30 hover:bg-emerald-950/25"
                  : "border-slate-800 bg-slate-950/80 text-slate-200 hover:border-slate-700 hover:bg-slate-900",
              )}
            >
              {personaPaused ? <PlayCircle className="h-3.5 w-3.5" /> : <PauseCircle className="h-3.5 w-3.5" />}
              {personaPaused ? "Resume" : "Pause"}
            </button>

            <Link
              href={activeSessionId ? `/persona/settings?session_id=${activeSessionId}` : "/persona/settings"}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/80 px-3 py-2 text-xs font-medium text-slate-200 transition-all hover:border-slate-700 hover:bg-slate-900"
            >
              <Settings className="h-3.5 w-3.5" />
              Settings
            </Link>
          </div>
        </div>

        {runtime.error ? (
          <div className="px-5 pb-3">
            <p className="text-xs text-rose-400/80">{runtime.error}</p>
          </div>
        ) : null}
      </header>

      <main className="min-h-0 flex-1">
        {persona ? (
          <UnifiedPersonaWorkspace
            persona={persona}
            agentSlug={persona.agent_slug}
            personaName={personaName}
            runtime={runtime}
            activeSessionId={activeSessionId}
            sidebarRefreshTrigger={sidebarRefreshTrigger}
            runtimeSyncKey={runtime.runtimeSyncKey}
            onSelectSession={handleSelectSession}
            onSessionCreated={handleSessionCreated}
            onNewSession={handleNewSession}
          />
        ) : personaError ? (
          <div className="h-full flex flex-col items-center justify-center gap-3 text-rose-400">
            <div className="rounded-full bg-rose-500/10 p-3">
              <AlertCircle className="h-5 w-5" />
            </div>
            <p className="text-sm font-medium">Failed to load persona</p>
            <p className="text-xs text-rose-500/80 max-w-md text-center">{personaError}</p>
          </div>
        ) : (
          <div className="h-full flex flex-col items-center justify-center gap-3">
            <div className="rounded-full bg-slate-800/50 p-3">
              <HeartPulse className="h-5 w-5 text-slate-600" />
            </div>
            <p className="text-sm font-medium text-slate-500">Persona not configured</p>
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
          <Loader2 className="h-6 w-6 animate-spin text-amber-500/50" />
        </div>
      }
    >
      <PersonaContent />
    </Suspense>
  );
}
