"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import type { EntitySummary } from "@/lib/memory-types";
import { EntityEpisodesList } from "./EntityEpisodesList";

interface EntityRowProps {
  entity: EntitySummary;
  groupId: string;
  isExpanded: boolean;
  onToggle: () => void;
  isOrphan: boolean;
  isDuplicate: boolean;
}

export function EntityRow({
  entity,
  groupId,
  isExpanded,
  onToggle,
  isOrphan,
  isDuplicate,
}: EntityRowProps) {
  return (
    <div className="border-b border-slate-800/50">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-slate-800/40 transition-colors"
      >
        {isExpanded ? (
          <ChevronDown className="h-3.5 w-3.5 text-slate-500 shrink-0" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-slate-500 shrink-0" />
        )}
        <span className="text-sm text-slate-200 font-medium truncate flex-1 min-w-0">
          {entity.name}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          {isOrphan && (
            <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-amber-500/10 text-amber-400 border border-amber-500/30">
              orphan
            </span>
          )}
          {isDuplicate && (
            <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-orange-500/10 text-orange-400 border border-orange-500/30">
              duplicate
            </span>
          )}
          <span className="px-1.5 py-0.5 text-[10px] font-medium rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/30">
            {entity.episode_count} ep
          </span>
          <span className="px-1.5 py-0.5 text-[10px] font-medium rounded-full bg-slate-700 text-slate-400 border border-slate-600">
            {entity.edge_count} edges
          </span>
          {entity.created_at && (
            <span className="text-[10px] text-slate-500 tabular-nums">
              {new Date(entity.created_at).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
              })}
            </span>
          )}
        </div>
      </button>
      {isExpanded && (
        <div className="bg-slate-900/40 border-t border-slate-800/50">
          <EntityEpisodesList entityName={entity.name} groupId={groupId} />
        </div>
      )}
    </div>
  );
}
