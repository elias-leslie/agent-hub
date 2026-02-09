import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SessionListItem, Session, SessionEventsResponse } from "@/lib/api";
import { estimateCost, formatCost, formatTokenPair, formatTokens, formatRelativeTime, COST_PER_1M_INPUT, COST_PER_1M_OUTPUT } from "../utils";
import { StatusCell } from "./StatusCell";
import { ModelPill } from "./ModelPill";
import { Tooltip } from "./Tooltip";
import { CopyIdButton } from "./CopyIdButton";
import { ExpandedRowContent } from "./ExpandedRowContent";

export function SessionTableRow({
  session,
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
    session.total_output_tokens
  );

  // Cost breakdown for tooltip
  const inputCost = (session.total_input_tokens * (COST_PER_1M_INPUT[session.model] || COST_PER_1M_INPUT.default)) / 1_000_000;
  const outputCost = (session.total_output_tokens * (COST_PER_1M_OUTPUT[session.model] || COST_PER_1M_OUTPUT.default)) / 1_000_000;

  return (
    <div
      data-testid="session-row"
      className={cn(
        "transition-all duration-300",
        isLive && "bg-emerald-50/50 dark:bg-emerald-950/10",
        isFocused && "bg-blue-50 dark:bg-blue-950/20 ring-1 ring-inset ring-blue-200 dark:ring-blue-800",
        isFlashing && "animate-flash"
      )}
    >
      {/* ROW */}
      <button
        onClick={() => onToggleExpand(session.id)}
        className="w-full grid grid-cols-[80px_minmax(120px,1fr)_minmax(140px,1.5fr)_130px_100px_80px_70px_36px] gap-3 px-4 py-2.5 items-center text-left hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors group"
      >
        {/* Status */}
        <StatusCell status={session.status} isLive={isLive} />

        {/* Project */}
        <div className="min-w-0">
          <span className="text-xs font-semibold text-slate-800 dark:text-slate-100 truncate block">
            {session.project_id}
          </span>
        </div>

        {/* Agent */}
        <div className="min-w-0">
          <span className="text-xs text-slate-500 dark:text-slate-400 truncate block">
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
          <span className="text-[11px] font-mono tabular-nums text-slate-600 dark:text-slate-300 cursor-help">
            {formatTokenPair(session.total_input_tokens, session.total_output_tokens)}
          </span>
        </Tooltip>

        {/* Cost */}
        <div className="text-right">
          <span className={cn(
            "text-[11px] font-mono tabular-nums font-medium",
            cost > 0.01
              ? "text-amber-600 dark:text-amber-400"
              : "text-slate-500 dark:text-slate-400"
          )}>
            {formatCost(cost)}
          </span>
        </div>

        {/* Time */}
        <div className="text-right">
          <span className="text-[11px] font-mono tabular-nums text-slate-500 dark:text-slate-400">
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
          <div className="border-t border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/80">
            <ExpandedRowContent
              session={session}
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
