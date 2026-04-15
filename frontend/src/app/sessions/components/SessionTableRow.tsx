import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SessionListItem, Session, SessionEventsResponse } from "@/lib/api";
import type { ModelCost } from "@/lib/models";
import { estimateCost, formatCost, formatTokenPair, formatTokens, formatRelativeTime } from "../utils";
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

  // Cost breakdown for tooltip
  const modelCost = resolveModelCost(session.model, modelCosts);
  const inputCost = (session.total_input_tokens * modelCost.input_per_m) / 1_000_000;
  const outputCost = (session.total_output_tokens * modelCost.output_per_m) / 1_000_000;

  return (
    <div
      data-testid="session-row"
      className={cn(
        "transition-all duration-300",
        isLive && "bg-emerald-950/10",
        isFocused && "bg-blue-950/20 ring-1 ring-inset ring-amber-800",
        isFlashing && "animate-flash"
      )}
    >
      {/* ROW */}
      <button
        onClick={() => onToggleExpand(session.id)}
        className="group grid w-full grid-cols-[80px_minmax(120px,1fr)_minmax(140px,1.5fr)_130px_100px_80px_70px_36px] items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-slate-800/30"
      >
        {/* Status */}
        <StatusCell status={session.status} isLive={isLive} />

        {/* Project */}
        <div className="min-w-0 space-y-1">
          <span className="text-xs font-semibold text-slate-100 truncate block">
            {session.project_id}
          </span>
          {session.attribution_label && (
            <span
              className={cn(
                "inline-flex rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em]",
                attributionTone(session.attribution_kind)
              )}
            >
              {session.attribution_label}
            </span>
          )}
        </div>

        {/* Agent */}
        <div className="min-w-0">
          <span className="text-xs text-slate-400 truncate block">
            {session.agent_slug || "—"}
          </span>
        </div>

        {/* Model - click to filter */}
        <ModelPill
          model={session.model}
          provider={session.provider}
          onClick={() => onModelFilterClick(session.model)}
          isActive={modelFilter === session.model}
        />

        {/* Tokens (In / Out) with cost breakdown tooltip */}
        <Tooltip
          content={
            <div className="space-y-0.5">
              <div>Input: {formatTokens(session.total_input_tokens)} ({formatCost(inputCost)})</div>
              <div>Output: {formatTokens(session.total_output_tokens)} ({formatCost(outputCost)})</div>
            </div>
          }
          position="top"
        >
          <span className="text-[11px] font-mono tabular-nums text-slate-300 cursor-help">
            {formatTokenPair(session.total_input_tokens, session.total_output_tokens)}
          </span>
        </Tooltip>

        {/* Cost */}
        <div className="text-right">
          <span className={cn(
            "text-[11px] font-mono tabular-nums font-medium",
            cost > 0.01
              ? "text-amber-400"
              : "text-slate-400"
          )}>
            {formatCost(cost)}
          </span>
        </div>

        {/* Time */}
        <div className="text-right">
          <span className="text-[11px] font-mono tabular-nums text-slate-400">
            {formatRelativeTime(session.updated_at)}
          </span>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-end gap-0.5">
          <div className="opacity-0 group-hover:opacity-100 transition-opacity">
            <CopyIdButton id={session.id} asSpan />
          </div>
          <ChevronDown
            className={cn(
              "h-4 w-4 text-slate-400 transition-transform duration-200",
              isExpanded && "rotate-180"
            )}
          />
        </div>
      </button>

      {/* EXPANDED CONTENT - Accordion push animation */}
      <div
        className={cn(
          "grid transition-all duration-300 ease-out",
          isExpanded
            ? "grid-rows-[1fr] opacity-100"
            : "grid-rows-[0fr] opacity-0"
        )}
      >
        <div className="overflow-hidden">
          <div className="border-t border-slate-700 bg-slate-900/80">
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
