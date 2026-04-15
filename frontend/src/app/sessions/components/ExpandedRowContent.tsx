import { RefreshCw, Gauge, Zap, TrendingUp, Maximize2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SessionListItem, Session, SessionEventsResponse } from "@/lib/api";
import type { ModelCost } from "@/lib/models";
import { EventTimeline } from "@/components/timeline";
import { estimateCost, formatCost, formatTokens, formatDuration } from "../utils";
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
        <RefreshCw className="h-4 w-4 animate-spin mr-2" />
        Loading session details...
      </div>
    );
  }

  if (!expandedData || !eventsData) {
    return (
      <div className="flex items-center justify-center py-16 text-sm text-slate-500">
        Failed to load session details
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

  return (
    <div className="flex flex-col bg-slate-900/95">
      {/* Stats Header Bar */}
      <div className="flex items-center gap-6 px-5 py-3 border-b border-slate-700/50 bg-slate-800/50">
        {/* Context Usage */}
        {expandedData.context_usage && (
          <div className="flex items-center gap-2">
            <Gauge className="h-3.5 w-3.5 text-slate-500" />
            <div className="flex items-center gap-2">
              <div className="w-24 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded-full transition-all",
                    expandedData.context_usage.percent_used > 90
                      ? "bg-red-500"
                      : expandedData.context_usage.percent_used > 70
                        ? "bg-amber-500"
                        : "bg-emerald-500"
                  )}
                  style={{
                    width: `${Math.min(100, expandedData.context_usage.percent_used)}%`,
                  }}
                />
              </div>
              <span className="text-[10px] font-mono tabular-nums text-slate-400">
                {expandedData.context_usage.percent_used.toFixed(0)}%
              </span>
            </div>
          </div>
        )}

        {/* Tokens */}
        <div className="flex items-center gap-1.5">
          <Zap className="h-3.5 w-3.5 text-emerald-500" />
          <span className="text-[10px] font-mono tabular-nums text-slate-300">
            {formatTokens(expandedData.total_input_tokens || 0)}
          </span>
          <span className="text-slate-600">/</span>
          <span className="text-[10px] font-mono tabular-nums text-slate-300">
            {formatTokens(expandedData.total_output_tokens || 0)}
          </span>
        </div>

        {/* Cost */}
        <div className="flex items-center gap-1.5">
          <TrendingUp className="h-3.5 w-3.5 text-amber-500" />
          <span className="text-[10px] font-mono tabular-nums text-amber-400">
            {formatCost(cost)}
          </span>
        </div>

        {/* Duration */}
        <div className="flex items-center gap-1.5 text-slate-500">
          <span className="text-[10px] font-mono tabular-nums">
            {formatDuration(expandedData.created_at, expandedData.updated_at)}
          </span>
        </div>

        {/* Events count */}
        <div className="flex items-center gap-1.5 text-slate-500">
          <span className="text-[10px]">
            {eventsData.total} events
          </span>
          <span className="text-slate-600">·</span>
          <span className="text-[10px]">
            {eventsData.max_turn} turns
          </span>
        </div>

        {live && (
          <div className="flex items-center gap-1.5 text-slate-400">
            <span className="text-[10px] font-mono">
              {live.health} · {live.phase}
            </span>
            {live.current_tool_name && (
              <>
                <span className="text-slate-600">·</span>
                <span className="text-[10px] font-mono">
                  {live.current_tool_name}
                </span>
              </>
            )}
          </div>
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Deep dive link */}
        <a
          href={`/sessions/${session.id}`}
          onClick={(e) => e.stopPropagation()}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[10px] font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-700/50 transition-colors"
        >
          <Maximize2 className="h-3 w-3" />
          Full view
        </a>

        {/* Copy ID */}
        <CopyIdButton id={session.id} />
      </div>

      {/* Event Timeline */}
      {live && (
        <div className="px-5 py-3 border-b border-slate-700/50 text-[11px] font-mono text-slate-400 space-y-1">
          {live.summary && <p>{live.summary}</p>}
          {(live.last_validation_command || live.last_command || live.last_read_path || live.last_write_path || live.stall_reason) && (
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
