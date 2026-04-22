"use client";

import { Suspense } from "react";
import {
  Activity,
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
import { ProvenanceBadge, ScopeChip } from "./components/persona-operator-chrome";

type RuntimeLabel = "Paused" | "Blocked" | "Waiting" | "Finalizing" | "Working" | "Auto-run off" | "Idle";

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
  if (!phase) return "Idle";
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
      ? " via scheduled trigger"
      : status.running_trigger === "manual"
        ? " via manual run"
        : "";
  return `Heartbeat running${scope}${trigger}`;
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
    return { text: `${args.personaName} is actively working`, source: "advisory" };
  }
  if (args.personaPaused) {
    return { text: `${args.personaName} is paused`, source: "session" };
  }
  if (args.heartbeatStatus?.last_run) {
    return {
      text: `Last heartbeat ${formatDistanceToNow(new Date(args.heartbeatStatus.last_run), { addSuffix: true })}`,
      source: "advisory",
    };
  }
  return { text: "Idle cockpit ready", source: "session" };
}

function isWorkActive(
  session: { status?: string; live_activity?: { status?: string; phase?: string } | null } | null | undefined,
): boolean {
  return Boolean(
    session
    && (
      session.status === "active"
      || session.live_activity?.status === "active"
      || session.live_activity?.phase === "running_tool"
      || session.live_activity?.phase === "waiting_for_model"
      || session.live_activity?.phase === "finalizing"
    ),
  );
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
    ? `Last heartbeat ${formatDistanceToNow(new Date(heartbeatStatus.last_run), { addSuffix: true })}`
    : "Never run";
  const executionState = persona?.execution_state ?? "active";
  const personaName = getPersonaDisplayName(persona?.name);
  const personaPaused = executionState === "paused";
  const autoRunDisabled = (persona?.heartbeat_interval_minutes ?? 0) === 0;
  const runtimeLabel = formatRuntimeLabel(runtime.primarySession?.live_activity?.phase, executionState, autoRunDisabled);
  const isActive = runtimeLabel === "Working" || runtimeLabel === "Waiting" || runtimeLabel === "Finalizing";
  const activeWorkCount = [...runtime.activePersonaSessions, ...runtime.activeChildSessions].reduce(
    (count, session) => count + (isWorkActive(session) ? 1 : 0),
    0,
  );
  const activeChildLaneCount = runtime.activeChildSessions.reduce(
    (count, session) => count + (isWorkActive(session) ? 1 : 0),
    0,
  );
  const liveSummary = buildLiveSummaryDescriptor({
    runtimeSummary: runtime.primarySession?.live_activity?.summary,
    heartbeatStatus,
    isHeartbeatRunning,
    personaPaused,
    personaName,
  });

  const handlePersonaPauseResume = async () => {
    updatePersona({ execution_state: personaPaused ? "active" : "paused" });
    if (!personaPaused && runtime.primarySession) {
      await runtime.stopCurrentStream();
    }
  };

  const handleStopCurrentStream = async () => {
    const result = await runtime.stopActiveWork();
    if (result.cancelled > 0) {
      toast.success(
        result.cancelled > 1
          ? `Stopped ${result.cancelled} live sessions for ${personaName}`
          : `Stopped live work for ${personaName}`,
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
        <Loader2 className="h-6 w-6 animate-spin text-amber-500/50" />
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col overflow-hidden bg-slate-950">
      <header className="sticky top-0 z-30 flex-shrink-0 border-b border-slate-800/60 bg-[linear-gradient(135deg,rgba(15,23,42,0.98),rgba(2,6,23,0.98))] backdrop-blur-xl">
        <div className="border-b border-slate-800/60 px-5 py-3">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative flex-shrink-0">
                  <span className={cn("block h-2.5 w-2.5 rounded-full transition-all", STATUS_DOT[runtimeLabel])} />
                </div>
                <h1 className="text-sm font-semibold tracking-wide text-slate-50 flex-shrink-0">
                  {personaName}
                </h1>
                <span className={cn(
                  "rounded-md px-2 py-0.5 text-[10px] font-medium tracking-wide uppercase flex-shrink-0",
                  isActive ? "bg-emerald-500/15 text-emerald-400" :
                  personaPaused ? "bg-amber-500/15 text-amber-400" :
                  runtimeLabel === "Blocked" ? "bg-rose-500/15 text-rose-400" :
                  "bg-slate-800 text-slate-500",
                )}>
                  {runtimeLabel}
                </span>
                <ProvenanceBadge source={liveSummary.source} />
                {autosave.status === "saving" || autosave.status === "scheduled" ? <ScopeChip>Saving operator state…</ScopeChip> : null}
                {autosave.status === "saved" ? <ScopeChip>Operator state saved</ScopeChip> : null}
                {autosave.status === "error" ? <ScopeChip tone="danger">Save failed</ScopeChip> : null}
              </div>
              <p className="mt-2 text-sm text-slate-300 xl:max-w-4xl">
                {liveSummary.text}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 xl:justify-end">
              <ScopeChip tone={activeChildLaneCount > 0 ? "warning" : "default"}>Active child lanes {activeChildLaneCount}</ScopeChip>
              <ScopeChip tone={activeWorkCount > 1 ? "warning" : "default"}>{activeWorkCount} live sessions</ScopeChip>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 px-5 py-3">
          <button
            onClick={handleHeartbeatTrigger}
            disabled={personaPaused || isHeartbeatRunning}
            aria-busy={isHeartbeatRunning}
            className={cn(
              "inline-flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-medium transition-all",
              personaPaused || isHeartbeatRunning
                ? "cursor-not-allowed border border-slate-800 bg-slate-900/70 text-slate-500"
                : "border border-slate-700 bg-slate-900/80 text-slate-200 hover:border-slate-600 hover:bg-slate-800",
            )}
            title={heartbeatTooltip}
          >
            <HeartPulse className={cn("h-3.5 w-3.5", isHeartbeatRunning && "animate-pulse text-amber-400")} />
            {isHeartbeatRunning ? "Heartbeat running" : "Heartbeat"}
          </button>

          <button
            onClick={handleStopCurrentStream}
            disabled={activeWorkCount === 0 || runtime.stoppingSessionId !== null}
            className="inline-flex items-center gap-2 rounded-xl border border-rose-500/20 bg-rose-950/20 px-3 py-2 text-xs font-medium text-rose-200 transition-all hover:border-rose-500/40 hover:bg-rose-950/30 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Square className="h-3.5 w-3.5" />
            {runtime.stoppingSessionId ? "Stopping active work…" : "Stop active work"}
          </button>

          <button
            onClick={handlePersonaPauseResume}
            className={cn(
              "inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-xs font-medium transition-all",
              personaPaused
                ? "border-emerald-500/20 bg-emerald-950/20 text-emerald-200 hover:border-emerald-400/30 hover:bg-emerald-950/30"
                : "border-slate-700 bg-slate-900/80 text-slate-200 hover:border-slate-600 hover:bg-slate-800",
            )}
          >
            {personaPaused ? <PlayCircle className="h-3.5 w-3.5" /> : <PauseCircle className="h-3.5 w-3.5" />}
            {personaPaused ? "Resume operator" : "Pause operator"}
          </button>

          <Link
            href="/persona/analytics"
            className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-3 py-2 text-xs font-medium text-slate-200 transition-all hover:border-slate-600 hover:bg-slate-800"
          >
            <Activity className="h-3.5 w-3.5" />
            Analytics
          </Link>

          <Link
            href={activeSessionId ? `/persona/settings?session_id=${activeSessionId}` : "/persona/settings"}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-3 py-2 text-xs font-medium text-slate-200 transition-all hover:border-slate-600 hover:bg-slate-800"
          >
            <Settings className="h-3.5 w-3.5" />
            Settings
          </Link>
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
