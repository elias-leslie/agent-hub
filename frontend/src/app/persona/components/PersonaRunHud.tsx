"use client";

import { formatDistanceToNowStrict } from "date-fns";
import {
  Activity,
  BrainCircuit,
  Clock3,
  FolderTree,
  Layers3,
  RefreshCw,
  Square,
  TerminalSquare,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { Session, SessionListItem } from "@/lib/api/sessions";
import type { PersonaRuntimeState } from "../hooks/usePersonaRuntime";
import { prettifyDisplayText, shortenText } from "./workspace-format";
import {
  CommandSurface,
  MetricCard,
  MetricStrip,
  ProvenanceBadge,
  ScopeChip,
} from "./persona-operator-chrome";

interface PersonaRunHudProps {
  personaName: string;
  runtime: PersonaRuntimeState;
  session?: SessionListItem | null;
  sessionDetails?: Session | null;
  onStop?: () => void;
  onRefresh: () => void;
  onOpenCommands: () => void;
  compact?: boolean;
}

function displayModelIdentity(provider: string | null | undefined, model: string | null | undefined): string {
  if (!model) return "none";
  if (provider && model.toLowerCase().startsWith(`${provider.toLowerCase()}/`)) {
    return model;
  }
  return provider ? `${provider}/${model}` : model;
}

export function PersonaRunHud({
  personaName,
  runtime,
  session,
  sessionDetails,
  onStop,
  onRefresh,
  onOpenCommands,
  compact = false,
}: PersonaRunHudProps) {
  const primary = session ?? runtime.primarySession;
  const details = sessionDetails ?? (primary?.id === runtime.primarySessionDetails?.id ? runtime.primarySessionDetails : null);
  const contextUsage = details?.context_usage ?? null;
  const liveActivity = primary?.live_activity ?? null;
  const elapsed = primary?.created_at
    ? formatDistanceToNowStrict(new Date(primary.created_at), { addSuffix: false })
    : "idle";
  const filesTouched = liveActivity?.files_touched?.length ?? 0;
  const activeChildLaneCount = runtime.activeChildSessions.filter(
    (child) => child.status === "active" || child.live_activity?.status === "active",
  ).length;
  const liveSummary = liveActivity?.summary
    ? shortenText(prettifyDisplayText(liveActivity.summary) || liveActivity.summary, compact ? 120 : 180)
    : null;
  const blockerSummary = liveActivity?.stall_reason || runtime.error || "None surfaced";
  const hasBlocker = blockerSummary !== "None surfaced";
  const stopEnabled = Boolean(primary && (primary.status === "active" || liveActivity?.status === "active"));

  return (
    <CommandSurface data-testid="persona-run-hud" className={compact ? "rounded-[22px]" : undefined}>
      <div className={cn(compact ? "p-3" : "p-4")}>
        <div className={cn("flex gap-3", compact ? "flex-col" : "flex-col gap-4 xl:flex-row xl:items-start xl:justify-between")}>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <ProvenanceBadge source={liveSummary ? "runtime" : "advisory"} />
              <ScopeChip tone={activeChildLaneCount > 0 ? "warning" : "default"}>
                Active child lanes · {activeChildLaneCount}
              </ScopeChip>
              <span className="rounded-full border border-slate-700/80 bg-slate-900/70 px-2.5 py-1 text-[11px] text-slate-300">
                {primary ? `${personaName} focused thread` : `${personaName} idle cockpit`}
              </span>
            </div>
            <h2 className={cn("mt-2 font-semibold tracking-tight text-slate-50", compact ? "line-clamp-2 text-sm" : "text-xl")}>
              {liveSummary || `No live runtime summary yet. Advisory controls stay available while ${personaName} sits idle.`}
            </h2>
            {!compact ? (
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">
                One command rail. Runtime truth first. Session-scoped stop only. Advisory controls stay labeled when backend scope stays advisory.
              </p>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onRefresh}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-2.5 py-1.5 text-xs font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh truth
            </button>
            <button
              type="button"
              onClick={onOpenCommands}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-2.5 py-1.5 text-xs font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
            >
              <TerminalSquare className="h-3.5 w-3.5" />
              Command deck
            </button>
            <button
              type="button"
              onClick={() => {
                if (onStop) {
                  onStop();
                  return;
                }
                void runtime.stopCurrentStream();
              }}
              disabled={!stopEnabled || runtime.stoppingSessionId !== null}
              className="inline-flex items-center gap-2 rounded-xl border border-rose-500/20 bg-rose-950/20 px-2.5 py-1.5 text-xs font-medium text-rose-200 transition hover:border-rose-400/30 hover:bg-rose-950/30 disabled:opacity-60"
            >
              <Square className="h-3.5 w-3.5" />
              {runtime.stoppingSessionId ? "Stopping" : "Stop active work"}
            </button>
          </div>
        </div>

        <MetricStrip className={compact ? "mt-3 grid-cols-2" : "mt-4 xl:grid-cols-6"}>
          <MetricCard
            icon={<Activity className="h-3.5 w-3.5" />}
            label="Runtime state"
            value={primary?.status || "idle"}
            detail={liveActivity?.status ? `Live beacon · ${liveActivity.status}` : "Session row only"}
            tone={primary ? "success" : "default"}
          />
          <MetricCard
            icon={<Activity className="h-3.5 w-3.5" />}
            label="Blocker"
            value={blockerSummary}
            detail={hasBlocker ? "Runtime/session blocker surfaced" : "No blocker surfaced"}
            tone={hasBlocker ? "warning" : "default"}
          />
          <MetricCard icon={<Clock3 className="h-3.5 w-3.5" />} label="Elapsed" value={elapsed} />
          <MetricCard
            icon={<Layers3 className="h-3.5 w-3.5" />}
            label="Child lanes"
            value={String(activeChildLaneCount)}
            detail="Counts child sessions only"
            tone={activeChildLaneCount > 0 ? "warning" : "default"}
          />
          <MetricCard
            icon={<BrainCircuit className="h-3.5 w-3.5" />}
            label="Model"
            value={displayModelIdentity(primary?.provider, primary?.model)}
          />
          <MetricCard
            icon={<FolderTree className="h-3.5 w-3.5" />}
            label="Context"
            value={contextUsage ? `${Math.round(contextUsage.percent_used)}%` : "n/a"}
            detail={contextUsage ? `${contextUsage.remaining_tokens.toLocaleString()} tokens left` : "No runtime metric"}
            tone={contextUsage && contextUsage.percent_used >= 80 ? "warning" : "default"}
          />
        </MetricStrip>

        <div className={cn("flex flex-wrap items-center gap-2 text-xs text-slate-400", compact ? "mt-2.5" : "mt-3")}>
          {liveActivity?.current_tool_name ? (
            <span className="rounded-full border border-sky-500/20 bg-sky-950/20 px-2.5 py-1 text-sky-200">
              Runtime tool · {liveActivity.current_tool_name}
            </span>
          ) : null}
          {liveActivity?.stall_reason ? (
            <span className="rounded-full border border-amber-500/20 bg-amber-950/20 px-2.5 py-1 text-amber-200">
              Stall · {liveActivity.stall_reason}
            </span>
          ) : null}
          {primary?.external_id ? (
            <span className="rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1">
              External · {primary.external_id}
            </span>
          ) : null}
          {details?.total_input_tokens || details?.total_output_tokens ? (
            <span className="rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1">
              Session tokens · {(details?.total_input_tokens ?? 0) + (details?.total_output_tokens ?? 0)}
            </span>
          ) : null}
        </div>
      </div>
    </CommandSurface>
  );
}
