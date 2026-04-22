import { Gauge, Maximize2, RefreshCw, TrendingUp, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SessionListItem, Session, SessionEventsResponse } from "@/lib/api";
import type { ModelCost } from "@/lib/models";
import { EventTimeline } from "@/components/timeline";
import {
  estimateCost,
  formatCost,
  formatDuration,
  formatTokens,
  getExecutionIdentity,
} from "../utils";
import { CopyIdButton } from "./CopyIdButton";

export function ExpandedRowContent({
  session,
  modelCosts,
  expandedData,
  eventsData,
  isLoading,
}: {
  session: SessionListItem;
  modelCosts: Map<string, ModelCost>;
  expandedData: Session | null;
  eventsData: SessionEventsResponse | null;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16 text-sm text-slate-500">
        <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
        Loading session evidence…
      </div>
    );
  }

  if (!expandedData || !eventsData) {
    return (
      <div className="px-5 py-10 text-sm text-slate-400">
        <div className="rounded-2xl border border-amber-500/20 bg-slate-950/80 p-5">
          <p className="text-sm font-semibold text-slate-100">
            Evidence unavailable for this session
          </p>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            Keep the row context in view and retry expansion when the backend is ready to serve the overview and timeline again.
          </p>
        </div>
      </div>
    );
  }

  const cost = estimateCost(
    session.model,
    expandedData.total_input_tokens || 0,
    expandedData.total_output_tokens || 0,
    modelCosts,
  );
  const live = expandedData.live_activity;
  const eventCount = expandedData.event_count ?? eventsData.total;
  const identity = getExecutionIdentity(expandedData);

  return (
    <div className="flex flex-col bg-slate-950/95">
      <div className="grid gap-4 border-b border-slate-800 bg-slate-900/80 px-5 py-4 md:grid-cols-[1.4fr_1fr]">
        <div className="space-y-2">
          <p className="text-[10px] font-mono uppercase tracking-[0.24em] text-slate-500">
            Execution identity
          </p>
          <div className="space-y-2 text-sm text-slate-300">
            {identity.showRequested && identity.requestedModel ? (
              <p className="font-mono text-slate-200">
                {identity.requestedModel} <span className="px-1 text-slate-600">→</span>{" "}
                {identity.effectiveModel}
              </p>
            ) : (
              <p className="font-mono text-slate-200">{identity.effectiveModel}</p>
            )}
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
              <span>
                Provider {identity.requestedProvider === identity.effectiveProvider
                  ? identity.effectiveProvider
                  : `${identity.requestedProvider} → ${identity.effectiveProvider}`}
              </span>
              {identity.fallbackUsed && (
                <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 font-mono uppercase tracking-[0.18em] text-amber-200">
                  Fallback{identity.fallbackReason ? `: ${identity.fallbackReason}` : ""}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-[10px] font-mono uppercase tracking-[0.24em] text-slate-500">
            Counts
          </p>
          <div className="flex flex-wrap gap-3 text-xs font-mono text-slate-300">
            <span>u+a:{expandedData.message_count ?? session.message_count}</span>
            <span>events:{eventCount}</span>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4 border-b border-slate-800/80 bg-slate-900/70 px-5 py-3 text-[11px] text-slate-400">
        {expandedData.context_usage && (
          <div className="flex items-center gap-2">
            <Gauge className="h-3.5 w-3.5 text-slate-500" />
            <div className="flex items-center gap-2">
              <div className="h-1.5 w-24 overflow-hidden rounded-full bg-slate-700">
                <div
                  className={cn(
                    "h-full rounded-full transition-all",
                    expandedData.context_usage.percent_used > 90
                      ? "bg-red-500"
                      : expandedData.context_usage.percent_used > 70
                        ? "bg-amber-500"
                        : "bg-emerald-500",
                  )}
                  style={{
                    width: `${Math.min(100, expandedData.context_usage.percent_used)}%`,
                  }}
                />
              </div>
              <span className="font-mono tabular-nums">
                {expandedData.context_usage.percent_used.toFixed(0)}%
              </span>
            </div>
          </div>
        )}

        <div className="flex items-center gap-1.5">
          <Zap className="h-3.5 w-3.5 text-emerald-400" />
          <span className="font-mono tabular-nums text-slate-200">
            {formatTokens(expandedData.total_input_tokens || 0)}
          </span>
          <span className="text-slate-600">/</span>
          <span className="font-mono tabular-nums text-slate-200">
            {formatTokens(expandedData.total_output_tokens || 0)}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <TrendingUp className="h-3.5 w-3.5 text-amber-400" />
          <span className="font-mono tabular-nums text-amber-300">{formatCost(cost)}</span>
        </div>

        <div className="font-mono tabular-nums text-slate-400">
          {formatDuration(expandedData.created_at, expandedData.updated_at)}
        </div>

        <div className="text-slate-400">
          {eventCount} events <span className="text-slate-600">·</span> {eventsData.max_turn} turns
        </div>

        {live && (
          <div className="text-slate-400">
            {live.health} <span className="text-slate-600">·</span> {live.phase}
            {live.current_tool_name && (
              <>
                <span className="text-slate-600"> · </span>
                {live.current_tool_name}
              </>
            )}
          </div>
        )}

        <div className="flex-1" />

        <a
          href={`/sessions/${session.id}`}
          onClick={(e) => e.stopPropagation()}
          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[11px] font-medium text-slate-300 transition-colors hover:bg-slate-800 hover:text-slate-100"
        >
          <Maximize2 className="h-3 w-3" />
          Full view
        </a>

        <CopyIdButton id={session.id} />
      </div>

      {live && (
        <div className="space-y-1 border-b border-slate-800/80 px-5 py-3 text-[11px] font-mono text-slate-400">
          {live.summary && <p>{live.summary}</p>}
          {(live.last_validation_command ||
            live.last_command ||
            live.last_read_path ||
            live.last_write_path ||
            live.stall_reason) && (
            <div className="space-y-1 break-all">
              {live.stall_reason && <p>{live.stall_reason}</p>}
              {live.last_validation_command && <p>validation: {live.last_validation_command}</p>}
              {!live.last_validation_command && live.last_command && <p>command: {live.last_command}</p>}
              {live.last_read_path && <p>read: {live.last_read_path}</p>}
              {live.last_write_path && <p>write: {live.last_write_path}</p>}
            </div>
          )}
        </div>
      )}

      <div className="h-[400px]">
        <EventTimeline events={eventsData.events} />
      </div>
    </div>
  );
}
