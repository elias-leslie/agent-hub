"use client";

import { useState } from "react";
import type { MemoryEpisode, MemoryCategory } from "@/lib/memory-api";
import { ScopePill } from "./ScopePill";
import { TierDropdown } from "./TierDropdown";
import { UsageStatsPane } from "./UsageStatsPane";
import { MetadataPane } from "./MetadataPane";
import { TriggerTaskTypes } from "./TriggerTaskTypes";
import { SimilarEpisodesList } from "./SimilarEpisodesList";
import { EditEpisodeModal } from "./EditEpisodeModal";

export function ExpandedRowContent({
  episode,
  onDelete,
  isDeleting,
  onTierChange,
  onEdit,
}: {
  episode: MemoryEpisode;
  onDelete: () => void;
  isDeleting: boolean;
  onTierChange?: (newCategory: MemoryCategory) => void;
  onEdit?: () => void;
}) {
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);

  // Filter out UUID-only entities
  const isUuid = (str: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(str);
  const readableEntities = episode.entities.filter((e) => !isUuid(e));

  return (
    <div className="px-5 py-4 space-y-3">
      {/* TOP BAR: pills + meta + actions */}
      <div className="flex items-start justify-between gap-4">
        {/* Left: scope, tier, source pills */}
        <div className="flex items-center gap-2 flex-wrap">
          <ScopePill scope={episode.scope} size="md" />
          <TierDropdown
            episodeUuid={episode.uuid}
            currentCategory={episode.category}
            onTierChange={onTierChange}
          />
          <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-slate-800 text-slate-400 uppercase">
            {episode.source}
          </span>
        </div>

        {/* Right: metadata + actions */}
        <MetadataPane
          episode={episode}
          onEdit={() => setIsEditModalOpen(true)}
          onDelete={onDelete}
          isDeleting={isDeleting}
        />
      </div>

      {/* CONTENT */}
      <div className="p-3 rounded-lg bg-slate-800/40 border border-slate-700/50">
        <p className="text-sm text-slate-300 whitespace-pre-wrap leading-relaxed">
          {episode.content}
        </p>
      </div>

      {/* BOTTOM: entities + triggers + stats + similar */}
      <div className="space-y-2.5">
        {/* Entities */}
        {readableEntities.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[9px] font-bold uppercase tracking-widest text-slate-500 mr-1">Entities</span>
            {readableEntities.map((entity, i) => (
              <span
                key={i}
                className="px-2 py-0.5 text-[10px] rounded-full bg-slate-800 text-slate-400 border border-slate-700"
              >
                {entity}
              </span>
            ))}
          </div>
        )}

        {/* Trigger Task Types - only for reference tier */}
        {episode.category === "reference" && (
          <TriggerTaskTypes
            episodeUuid={episode.uuid}
            initialTriggerTypes={episode.trigger_task_types || []}
          />
        )}

        {/* Stats bar + Similar button */}
        <div className="flex items-center justify-between gap-3 pt-1 border-t border-slate-800/50">
          <UsageStatsPane
            loadedCount={episode.loaded_count}
            referencedCount={episode.referenced_count}
            helpfulCount={episode.helpful_count}
            harmfulCount={episode.harmful_count}
            utilityScore={episode.utility_score}
          />
          <SimilarEpisodesList episodeUuid={episode.uuid} />
        </div>
      </div>

      {/* Edit Modal */}
      <EditEpisodeModal
        episode={episode}
        isOpen={isEditModalOpen}
        onClose={() => setIsEditModalOpen(false)}
        onSaved={() => onEdit?.()}
      />
    </div>
  );
}
