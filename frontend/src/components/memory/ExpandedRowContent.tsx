"use client";

import { useState } from "react";
import type { MemoryEpisode, MemoryCategory } from "@/lib/memory-api";
import { ScopePill } from "./ScopePill";
import { TierDropdown } from "./TierDropdown";
import { TriggerTaskTypes } from "./TriggerTaskTypes";
import { UsageStatsPane } from "./UsageStatsPane";
import { MetadataPane } from "./MetadataPane";
import { CitationsList } from "./CitationsList";
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

  const handleEditModalOpen = () => {
    setIsEditModalOpen(true);
  };

  const handleEditModalClose = () => {
    setIsEditModalOpen(false);
  };

  const handleEditSaved = () => {
    onEdit?.();
  };

  // Filter out UUID-only entities (not human-readable)
  const isUuid = (str: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(str);
  const readableEntities = episode.entities.filter(e => !isUuid(e));

  return (
    <div className="p-5 space-y-5">
      {/* Three-column layout: Content | Stats | Meta */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_200px_220px] gap-5">
        {/* CONTENT PANE */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 flex-wrap">
            <ScopePill scope={episode.scope} size="md" />

            <TierDropdown
              episodeUuid={episode.uuid}
              currentCategory={episode.category}
              onTierChange={onTierChange}
            />

            <span className="px-2 py-1 rounded text-[10px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 uppercase">
              {episode.source}
            </span>
          </div>

          <div className="p-4 rounded-lg bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
            <p className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap leading-relaxed">
              {episode.content}
            </p>
          </div>

          {/* Entity Tags - only show if entities contain human-readable names (not UUIDs) */}
          {readableEntities.length > 0 && (
            <div>
              <h4 className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">
                Entities
              </h4>
              <div className="flex flex-wrap gap-1.5">
                {readableEntities.map((entity, i) => (
                  <span
                    key={i}
                    className="px-2 py-1 text-[10px] rounded-full bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700"
                  >
                    {entity}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Trigger Task Types - only for reference tier */}
          {episode.category === "reference" && (
            <TriggerTaskTypes
              episodeUuid={episode.uuid}
              initialTriggerTypes={episode.trigger_task_types || []}
            />
          )}
        </div>

        {/* STATS PANE */}
        <UsageStatsPane
          episodeUuid={episode.uuid}
          loadedCount={episode.loaded_count}
          referencedCount={episode.referenced_count}
          helpfulCount={episode.helpful_count}
          harmfulCount={episode.harmful_count}
          utilityScore={episode.utility_score}
        />

        {/* META PANE */}
        <MetadataPane
          episode={episode}
          onEdit={handleEditModalOpen}
          onDelete={onDelete}
          isDeleting={isDeleting}
        />
      </div>

      {/* Citations & Similar — lazy-loaded */}
      <div className="flex gap-2 flex-wrap">
        <CitationsList episodeUuid={episode.uuid} />
        <SimilarEpisodesList episodeUuid={episode.uuid} />
      </div>

      {/* Edit Modal */}
      <EditEpisodeModal
        episode={episode}
        isOpen={isEditModalOpen}
        onClose={handleEditModalClose}
        onSaved={handleEditSaved}
      />
    </div>
  );
}
