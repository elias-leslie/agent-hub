"use client";

import type { ReactNode } from "react";
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
import { ProvenanceBadge, ScopeChip } from "./persona-operator-chrome";

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

function StatChip({
  icon,
  label,
  value,
  tone = "default",
}: {
  icon: ReactNode;
  label: string;
  value: string;
  tone?: "default" | "success" | "warning";
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border px-3 py-2",
        tone === "success"
          ? "border-emerald-500/20 bg-emerald-950/20 text-emerald-200"
          : tone === "warning"
            ? "border-amber-500/20 bg-amber-950/20 text-amber-200"
            : "border-slate-800/70 bg-slate-950/70 text-slate-200",
      )}
    >
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-slate-500">
        <span className="text-slate-400">{icon}</span>
        {label}
      </div>
      <div className="mt-1 text-sm font-medium">{value}</div>
    </div>
  );
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
  const activeChildLaneCount = runtime.activeChildSessions.length;
  const liveSummary = liveActivity?.summary
    ? shortenText(prettifyDisplayText(liveActivity.summary) || liveActivity.summary, compact ? 120 : 180)
    : null;
  const blockerSummary = liveActivity?.stall_reason || runtime.error || "None surfaced";
  const hasBlocker = blockerSummary !== "None surfaced";
  const stopLabel = primary?.parent_session_id ? "Stop selected lane" : "Stop focused thread";

  return (
    <section
      data-testid="persona-run-hud"
      className={cn(
        "overflow-hidden border border-slate-800/70 bg-[radial-gradient(circle_at_top_left,rgba(16,185,129,0.08),transparent_28%),radial-gradient(circle_at_bottom_right,rgba(56,189,248,0.08),transparent_28%),rgba(2,6,23,0.96)] shadow-[0_20px_60px_-36px_rgba(15,23,42,0.9)]",
        compact ? "rounded-[22px] p-3" : "rounded-[28px] p-4",
      )}
    >
      <div className={cn("flex gap-3", compact ? "flex-col" : "flex-col gap-4 xl:flex-row xl:items-start xl:justify-between")}>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <ProvenanceBadge source="runtime" />
            <ScopeChip tone={activeChildLaneCount > 0 ? "warning" : "default"}>
              Active child lanes {activeChildLaneCount}
            </ScopeChip>
            <span className="rounded-full border border-slate-700/80 bg-slate-900/70 px-2.5 py-1 text-[11px] text-slate-300">
              {primary ? `${personaName} active` : `${personaName} idle`}
            </span>
          </div>
          <h2 className={cn("mt-2 font-semibold tracking-tight text-slate-50", compact ? "line-clamp-2 text-sm" : "text-xl")}>
            {liveSummary || `See what ${personaName} is doing without digging through the feed.`}
          </h2>
          {!compact ? (
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">
              Runtime tool activity, context pressure, files touched, and live child-lane count stay visible while you steer.
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
            Refresh
          </button>
          <button
            type="button"
            onClick={onOpenCommands}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-2.5 py-1.5 text-xs font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
          >
            <TerminalSquare className="h-3.5 w-3.5" />
            Command deck
          </button>
          {primary ? (
            <button
              type="button"
              onClick={() => {
                if (onStop) {
                  onStop();
                  return;
                }
                void runtime.stopCurrentStream();
              }}
              disabled={runtime.stoppingSessionId !== null}
              className="inline-flex items-center gap-2 rounded-xl border border-rose-500/20 bg-rose-950/20 px-2.5 py-1.5 text-xs font-medium text-rose-200 transition hover:border-rose-400/30 hover:bg-rose-950/30 disabled:opacity-60"
            >
              <Square className="h-3.5 w-3.5" />
              {runtime.stoppingSessionId ? "Stopping" : stopLabel}
            </button>
          ) : null}
        </div>
      </div>

      {compact ? (
        <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
          <span className="rounded-full border border-emerald-500/20 bg-emerald-950/20 px-2.5 py-1 text-emerald-200">
            Status · {primary?.status || "idle"}
          </span>
          <span className={cn(
            "rounded-full border px-2.5 py-1",
            hasBlocker ? "border-amber-500/20 bg-amber-950/20 text-amber-200" : "border-slate-700 bg-slate-950/70 text-slate-300",
          )}>
            Blocker · {blockerSummary}
          </span>
          <span className="rounded-full border border-slate-700 bg-slate-950/70 px-2.5 py-1 text-slate-300">
            Elapsed · {elapsed}
          </span>
          <span className={cn(
            "rounded-full border px-2.5 py-1",
            activeChildLaneCount > 0 ? "border-amber-500/20 bg-amber-950/20 text-amber-200" : "border-slate-700 bg-slate-950/70 text-slate-300",
          )}>
            Active child lanes · {activeChildLaneCount}
          </span>
          <span className="rounded-full border border-slate-700 bg-slate-950/70 px-2.5 py-1 text-slate-300">
            Model · {displayModelIdentity(primary?.provider, primary?.model)}
          </span>
          <span className={cn(
            "rounded-full border px-2.5 py-1",
            contextUsage && contextUsage.percent_used >= 80
              ? "border-amber-500/20 bg-amber-950/20 text-amber-200"
              : "border-slate-700 bg-slate-950/70 text-slate-300",
          )}>
            Context · {contextUsage ? `${Math.round(contextUsage.percent_used)}%` : "n/a"}
          </span>
        </div>
      ) : (
        <div className="mt-4 grid gap-2.5 md:grid-cols-2 xl:grid-cols-7">
          <StatChip icon={<Activity className="h-3.5 w-3.5" />} label="Status" value={primary?.status || "idle"} tone={primary ? "success" : "default"} />
          <StatChip
            icon={<Activity className="h-3.5 w-3.5" />}
            label="Blocker"
            value={blockerSummary}
            tone={hasBlocker ? "warning" : "default"}
          />
          <StatChip icon={<Clock3 className="h-3.5 w-3.5" />} label="Elapsed" value={elapsed} />
          <StatChip icon={<Layers3 className="h-3.5 w-3.5" />} label="Active child lanes" value={String(activeChildLaneCount)} tone={activeChildLaneCount > 0 ? "warning" : "default"} />
          <StatChip icon={<BrainCircuit className="h-3.5 w-3.5" />} label="Model" value={displayModelIdentity(primary?.provider, primary?.model)} />
          <StatChip
            icon={<FolderTree className="h-3.5 w-3.5" />}
            label="Files"
            value={filesTouched > 0 ? String(filesTouched) : "none"}
          />
          <StatChip
            icon={<Activity className="h-3.5 w-3.5" />}
            label="Context"
            value={contextUsage ? `${Math.round(contextUsage.percent_used)}%` : "n/a"}
            tone={contextUsage && contextUsage.percent_used >= 80 ? "warning" : "default"}
          />
        </div>
      )}

      <div className={cn("flex flex-wrap items-center gap-2 text-xs text-slate-400", compact ? "mt-2.5" : "mt-3")}>
        {liveActivity?.current_tool_name ? (
          <span className="rounded-full border border-sky-500/20 bg-sky-950/20 px-2.5 py-1 text-sky-200">
            Tool: {liveActivity.current_tool_name}
          </span>
        ) : null}
        {liveActivity?.stall_reason ? (
          <span className="rounded-full border border-amber-500/20 bg-amber-950/20 px-2.5 py-1 text-amber-200">
            Stall: {liveActivity.stall_reason}
          </span>
        ) : null}
        {primary?.external_id ? (
          <span className="rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1">
            External: {primary.external_id}
          </span>
        ) : null}
        {details?.total_input_tokens || details?.total_output_tokens ? (
          <span className="rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1">
            Tokens: {(details?.total_input_tokens ?? 0) + (details?.total_output_tokens ?? 0)}
          </span>
        ) : null}
      </div>
    </section>
  );
}
