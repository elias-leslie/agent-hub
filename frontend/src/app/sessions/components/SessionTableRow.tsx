import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SessionListItem, Session, SessionEventsResponse } from "@/lib/api";
import type { ModelCost } from "@/lib/models";
import {
  estimateCost,
  formatCost,
  formatRelativeTime,
  formatTokenPair,
  formatTokens,
  getExecutionIdentity,
} from "../utils";
import { resolveModelCost } from "@/lib/model-pricing";
import { StatusCell } from "./StatusCell";
import { ModelPill } from "./ModelPill";
import { Tooltip } from "@/components/memory/Tooltip";
import { CopyIdButton } from "./CopyIdButton";
import { ExpandedRowContent } from "./ExpandedRowContent";

function attributionTone(kind?: string | null): string {
  switch (kind) {
    case "benchmark":
      return "border-amber-500/30 bg-amber-500/10 text-amber-200";
    case "autonomous":
      return "border-sky-500/30 bg-sky-500/10 text-sky-200";
    case "verification":
      return "border-emerald-500/30 bg-emerald-500/10 text-emerald-200";
    case "system":
      return "border-violet-500/30 bg-violet-500/10 text-violet-200";
    case "consultation":
      return "border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-200";
    default:
      return "border-slate-700 bg-slate-800/70 text-slate-300";
  }
}

export function SessionTableRow({
  session,
  modelCosts,
  isExpanded,
  isLive,
  isFocused,
  isFlashing,
  modelFilter,
  expandedSessionData,
  expandedEventsData,
  isLoadingDetails,
  onToggleExpand,
  onModelFilterClick,
}: {
  session: SessionListItem;
  modelCosts: Map<string, ModelCost>;
  isExpanded: boolean;
  isLive: boolean;
  isFocused: boolean;
  isFlashing: boolean;
  modelFilter: string;
  expandedSessionData: Session | null;
  expandedEventsData: SessionEventsResponse | null;
  isLoadingDetails: boolean;
  onToggleExpand: (sessionId: string) => void;
  onModelFilterClick: (model: string) => void;
}) {
  const cost = estimateCost(
    session.model,
    session.total_input_tokens,
    session.total_output_tokens,
    modelCosts,
  );
  const modelCost = resolveModelCost(session.model, modelCosts);
  const inputCost = (session.total_input_tokens * modelCost.input_per_m) / 1_000_000;
  const outputCost = (session.total_output_tokens * modelCost.output_per_m) / 1_000_000;
  const identity = getExecutionIdentity(session);
  const expandLabel = `${isExpanded ? "Collapse" : "Expand"} session ${session.id}`;

  return (
    <div
      data-testid="session-row"
      className={cn(
        "transition-all duration-200",
        isLive && "bg-emerald-950/10",
        isFocused && "ring-1 ring-inset ring-amber-800 bg-blue-950/20",
        isFlashing && "animate-flash",
      )}
    >
      <div className="grid grid-cols-[92px_minmax(220px,1.25fr)_minmax(170px,0.95fr)_minmax(240px,1.4fr)_110px_90px_90px_76px] items-start gap-3 px-5 py-4 transition-colors hover:bg-slate-900/40">
        <StatusCell status={session.status} liveActivity={session.live_activity} />

        <div className="min-w-0 space-y-1.5">
          <span className="block truncate text-sm font-semibold text-slate-100">
            {session.project_id}
          </span>
          {session.summary_oneliner ? (
            <p className="truncate text-[11px] text-slate-400">{session.summary_oneliner}</p>
          ) : (
            <p className="truncate text-[11px] text-slate-500">{session.id}</p>
          )}
          {session.attribution_label && (
            <span
              className={cn(
                "inline-flex rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em]",
                attributionTone(session.attribution_kind),
              )}
            >
              {session.attribution_label}
            </span>
          )}
        </div>

        <div className="min-w-0 space-y-1.5">
          <span className="block truncate text-xs font-medium text-slate-200">
            {session.agent_slug || "—"}
          </span>
          <div className="flex flex-wrap items-center gap-2 text-[10px] font-mono uppercase tracking-[0.12em] text-slate-500">
            <span>u+a:{session.message_count}</span>
            {session.event_count !== null && session.event_count !== undefined && (
              <span>events:{session.event_count}</span>
            )}
          </div>
        </div>

        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <ModelPill
              model={identity.effectiveModel}
              provider={identity.effectiveProvider ?? session.provider}
              onClick={() => onModelFilterClick(session.model)}
              isActive={modelFilter === session.model}
            />
            {identity.fallbackUsed && (
              <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-mono uppercase tracking-[0.18em] text-amber-200">
                Fallback{identity.fallbackReason ? `: ${identity.fallbackReason}` : ""}
              </span>
            )}
          </div>
          {identity.showRequested && identity.requestedModel ? (
            <p className="truncate text-[11px] font-mono text-slate-400">
              {identity.requestedModel}
              <span className="px-1 text-slate-600">→</span>
              {identity.effectiveModel}
            </p>
          ) : (
            <p className="truncate text-[11px] font-mono text-slate-500">
              {identity.effectiveProvider}
            </p>
          )}
        </div>

        <Tooltip
          content={
            <div className="space-y-0.5 text-[11px]">
              <div>
                Input: {formatTokens(session.total_input_tokens)} ({formatCost(inputCost)})
              </div>
              <div>
                Output: {formatTokens(session.total_output_tokens)} ({formatCost(outputCost)})
              </div>
            </div>
          }
          position="top"
        >
          <span className="cursor-help text-right text-[11px] font-mono tabular-nums text-slate-300">
            {formatTokenPair(session.total_input_tokens, session.total_output_tokens)}
          </span>
        </Tooltip>

        <div className="text-right">
          <span
            className={cn(
              "text-[11px] font-mono font-medium tabular-nums",
              cost > 0.01 ? "text-amber-300" : "text-slate-400",
            )}
          >
            {formatCost(cost)}
          </span>
        </div>

        <div className="text-right">
          <span className="text-[11px] font-mono tabular-nums text-slate-400">
            {formatRelativeTime(session.updated_at)}
          </span>
        </div>

        <div className="flex items-center justify-end gap-1">
          <CopyIdButton id={session.id} className="focus-visible:ring-2 focus-visible:ring-amber-400/50" />
          <button
            type="button"
            aria-expanded={isExpanded}
            aria-controls={`session-details-${session.id}`}
            aria-label={expandLabel}
            onClick={() => onToggleExpand(session.id)}
            className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-800 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50"
          >
            <ChevronDown
              className={cn(
                "h-4 w-4 transition-transform duration-200",
                isExpanded && "rotate-180",
              )}
            />
          </button>
        </div>
      </div>

      <div
        id={`session-details-${session.id}`}
        className={cn(
          "grid transition-all duration-300 ease-out",
          isExpanded ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0",
        )}
      >
        <div className="overflow-hidden">
          <div className="border-t border-slate-800 bg-slate-950/90">
            <ExpandedRowContent
              session={session}
              modelCosts={modelCosts}
              expandedData={isExpanded ? expandedSessionData : null}
              eventsData={isExpanded ? expandedEventsData : null}
              isLoading={isExpanded && isLoadingDetails}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
