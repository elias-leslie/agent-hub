import { Maximize2, RefreshCw } from "lucide-react";

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
      <div className="flex items-center justify-center py-12 text-sm text-slate-500">
        <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
        Loading session evidence…
      </div>
    );
  }

  if (!expandedData || !eventsData) {
    return <div className="px-4 py-6 text-sm text-slate-500">Session evidence unavailable.</div>;
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
  const liveNotes = [
    live?.stall_reason,
    live?.last_validation_command ? `validation: ${live.last_validation_command}` : null,
    !live?.last_validation_command && live?.last_command ? `command: ${live.last_command}` : null,
    live?.last_read_path ? `read: ${live.last_read_path}` : null,
    live?.last_write_path ? `write: ${live.last_write_path}` : null,
  ].filter(Boolean);

  return (
    <div className="flex flex-col bg-slate-950/92">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-800/80 px-4 py-3 text-[11px] text-slate-400">
        <span className="font-mono text-slate-200">
          {identity.showRequested && identity.requestedModel
            ? `${identity.requestedModel} → ${identity.effectiveModel}`
            : identity.effectiveModel}
        </span>
        <span>{identity.effectiveProvider}</span>
        {identity.fallbackUsed ? <span className="text-amber-300">fallback {identity.fallbackReason || "used"}</span> : null}
        <span>{formatTokens(expandedData.total_input_tokens || 0)} / {formatTokens(expandedData.total_output_tokens || 0)}</span>
        <span className="text-amber-300">{formatCost(cost)}</span>
        <span>{formatDuration(expandedData.created_at, expandedData.updated_at)}</span>
        <span>{eventCount} events</span>
        {live ? <span>{live.health} · {live.phase}</span> : null}
        <div className="flex-1" />
        <a
          href={`/sessions/${session.id}`}
          onClick={(e) => e.stopPropagation()}
          className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-medium text-slate-300 transition-colors hover:bg-slate-800 hover:text-slate-100"
        >
          <Maximize2 className="h-3 w-3" />
          Full view
        </a>
        <CopyIdButton id={session.id} />
      </div>

      {live?.summary || liveNotes.length > 0 ? (
        <div className="space-y-1 border-b border-slate-800/80 px-4 py-3 text-[11px] font-mono text-slate-400">
          {live?.summary ? <p className="text-slate-300">{live.summary}</p> : null}
          {liveNotes.map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>
      ) : null}

      <div className="h-[320px]">
        <EventTimeline events={eventsData.events} />
      </div>
    </div>
  );
}
