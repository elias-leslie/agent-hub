import { ChevronDown } from "lucide-react";

import { Tooltip } from "@/components/memory/Tooltip";
import { cn } from "@/lib/utils";
import type { SessionListItem, Session, SessionEventsResponse } from "@/lib/api";
import type { ModelCost } from "@/lib/models";
import { resolveModelCost } from "@/lib/model-pricing";
import {
  estimateCost,
  formatCost,
  formatRelativeTime,
  formatTokenPair,
  formatTokens,
  getExecutionIdentity,
} from "../utils";
import { CopyIdButton } from "./CopyIdButton";
import { ExpandedRowContent } from "./ExpandedRowContent";
import { ModelPill } from "./ModelPill";
import { StatusCell } from "./StatusCell";

function getSessionSecondaryLine(session: SessionListItem): string {
  const summary = session.summary_oneliner?.trim();
  if (summary) {
    return summary;
  }
  return `session ${session.id.slice(0, 8)}`;
}

function getUsageCopy(session: SessionListItem, cost: number) {
  const isActive = session.status === "active" || session.live_activity?.status === "active";
  if (isActive && session.total_input_tokens === 0 && session.total_output_tokens === 0) {
    return {
      primary: "live · collecting",
      secondary: "usage pending",
    };
  }
  const tokenPair = formatTokenPair(session.total_input_tokens, session.total_output_tokens);
  if (isActive) {
    return {
      primary: `live · ${tokenPair}`,
      secondary: formatCost(cost),
    };
  }
  return {
    primary: tokenPair,
    secondary: formatCost(cost),
  };
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
  const isActiveSession = session.status === "active" || session.live_activity?.status === "active";
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
  const usageCopy = getUsageCopy(session, cost);
  const hasKnownZeroUsage = session.total_input_tokens === 0 && session.total_output_tokens === 0;
  const hasSettledZeroUsage = hasKnownZeroUsage && !isActiveSession;
  const sessionSecondaryLine = getSessionSecondaryLine(session);
  const expandLabel = `${isExpanded ? "Collapse" : "Expand"} session ${session.id}`;

  return (
    <div
      data-testid="session-row"
      className={cn(
        "transition-colors duration-200",
        isLive && "border-l border-amber-400/60",
        isFocused && "bg-slate-900/60 ring-1 ring-inset ring-amber-500/30",
        isFlashing && "animate-flash",
      )}
    >
      <div className="grid grid-cols-[minmax(260px,1.6fr)_minmax(130px,0.8fr)_minmax(240px,1.2fr)_minmax(130px,0.8fr)_88px_76px] items-start gap-4 px-4 py-3 hover:bg-slate-900/30">
        <div className="min-w-0 space-y-1.5">
          <StatusCell status={session.status} liveActivity={session.live_activity} />
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-slate-100">{session.project_id}</div>
            <div className="truncate text-[11px] text-slate-400" title={session.summary_oneliner || session.id}>
              {sessionSecondaryLine}
            </div>
          </div>
        </div>

        <div className="min-w-0 space-y-1">
          <div className="truncate text-sm text-slate-200">{session.agent_slug || "—"}</div>
          <div className="truncate text-[11px] text-slate-500">
            {session.message_count} msg
            {session.event_count !== null && session.event_count !== undefined ? ` · ${session.event_count} evt` : ""}
          </div>
        </div>

        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <ModelPill
              model={identity.effectiveModel}
              provider={identity.effectiveProvider ?? session.provider}
              onClick={() => onModelFilterClick(session.model)}
              isActive={modelFilter === session.model}
              fallbackUsed={identity.fallbackUsed}
            />
          </div>
          {identity.showRequested && identity.requestedModel ? (
            <div className="truncate text-[11px] font-mono text-slate-500">
              {identity.requestedModel}
              <span className="px-1 text-slate-700">→</span>
              {identity.effectiveModel}
            </div>
          ) : (
            <div className="truncate text-[11px] font-mono text-slate-600">{identity.effectiveProvider}</div>
          )}
          {identity.fallbackUsed && identity.fallbackReason ? (
            <div className="truncate text-[10px] uppercase tracking-[0.14em] text-slate-600">
              fallback · {identity.fallbackReason}
            </div>
          ) : null}
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
              {hasSettledZeroUsage ? <div className="text-slate-500">Recorded zero usage</div> : null}
            </div>
          }
          position="top"
        >
          <div className="cursor-help text-right">
            <div className={cn(
              "text-[11px] font-mono tabular-nums",
              hasSettledZeroUsage ? "text-slate-500" : "text-slate-300",
            )}>
              {usageCopy.primary}
            </div>
            <div className={cn(
              "text-[11px] font-mono tabular-nums",
              hasSettledZeroUsage ? "text-slate-700" : "text-slate-600",
            )}>
              {usageCopy.secondary}
            </div>
          </div>
        </Tooltip>

        <div className="pt-0.5 text-right text-[11px] font-mono tabular-nums text-slate-400">
          {formatRelativeTime(session.updated_at)}
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
          <div className="border-t border-slate-800/70 bg-slate-950/80">
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
