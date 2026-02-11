"use client";

import { useState, useCallback } from "react";
import { Tag, X, Plus, Loader2 } from "lucide-react";
import type { MemoryEpisode, MemoryCategory } from "@/lib/memory-api";
import { getEpisodeTags, setEpisodeTags, getAllTags } from "@/lib/api/memory-tags";
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
  const [isEditingTags, setIsEditingTags] = useState(false);
  const [editTags, setEditTags] = useState<string[]>(episode.tags || []);
  const [tagInput, setTagInput] = useState("");
  const [isSavingTags, setIsSavingTags] = useState(false);
  const [allTags, setAllTags] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);

  const handleEditModalOpen = () => {
    setIsEditModalOpen(true);
  };

  const handleEditModalClose = () => {
    setIsEditModalOpen(false);
  };

  const handleEditSaved = () => {
    onEdit?.();
  };

  const handleStartEditTags = useCallback(async () => {
    setIsEditingTags(true);
    setEditTags(episode.tags || []);
    const tags = await getAllTags().catch(() => []);
    setAllTags(tags);
  }, [episode.tags]);

  const handleSaveTags = useCallback(async () => {
    setIsSavingTags(true);
    await setEpisodeTags(episode.uuid, editTags).catch(() => {});
    setIsSavingTags(false);
    setIsEditingTags(false);
    onEdit?.();
  }, [episode.uuid, editTags, onEdit]);

  const handleAddTag = useCallback((tag: string) => {
    const trimmed = tag.trim().toLowerCase();
    if (trimmed && !editTags.includes(trimmed)) {
      setEditTags((prev) => [...prev, trimmed]);
    }
    setTagInput("");
    setShowSuggestions(false);
  }, [editTags]);

  const handleRemoveTag = useCallback((tag: string) => {
    setEditTags((prev) => prev.filter((t) => t !== tag));
  }, []);

  const filteredSuggestions = allTags.filter(
    (t) => t.includes(tagInput.toLowerCase()) && !editTags.includes(t)
  ).slice(0, 6);

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

          {/* Tags */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <h4 className="text-[10px] font-bold uppercase tracking-widest text-slate-400">
                Tags
              </h4>
              {!isEditingTags && (
                <button
                  onClick={(e) => { e.stopPropagation(); handleStartEditTags(); }}
                  className="text-[10px] text-slate-500 hover:text-emerald-400 transition-colors"
                >
                  edit
                </button>
              )}
            </div>
            {isEditingTags ? (
              <div className="space-y-2">
                <div className="flex flex-wrap gap-1.5">
                  {editTags.map((tag) => (
                    <span
                      key={tag}
                      className="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] rounded-full bg-emerald-900/30 text-emerald-400 border border-emerald-500/30"
                    >
                      {tag}
                      <button
                        onClick={() => handleRemoveTag(tag)}
                        className="hover:text-red-400 transition-colors"
                      >
                        <X className="w-2.5 h-2.5" />
                      </button>
                    </span>
                  ))}
                </div>
                <div className="relative">
                  <input
                    type="text"
                    value={tagInput}
                    onChange={(e) => { setTagInput(e.target.value); setShowSuggestions(true); }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && tagInput.trim()) {
                        e.preventDefault();
                        handleAddTag(tagInput);
                      }
                    }}
                    onFocus={() => setShowSuggestions(true)}
                    onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
                    placeholder="Add tag..."
                    className="w-48 px-2 py-1 text-xs rounded border border-slate-700 bg-slate-800 text-slate-200 focus:outline-none focus:ring-1 focus:ring-emerald-500/40"
                  />
                  {showSuggestions && tagInput && filteredSuggestions.length > 0 && (
                    <div className="absolute top-full mt-1 left-0 w-48 rounded-lg border border-slate-700 bg-slate-900 shadow-xl z-20 overflow-hidden">
                      {filteredSuggestions.map((s) => (
                        <button
                          key={s}
                          onMouseDown={(e) => { e.preventDefault(); handleAddTag(s); }}
                          className="w-full text-left px-2 py-1.5 text-xs text-slate-300 hover:bg-slate-800 transition-colors"
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={handleSaveTags}
                    disabled={isSavingTags}
                    className="px-3 py-1 text-xs rounded bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-50 transition-colors"
                  >
                    {isSavingTags ? <Loader2 className="w-3 h-3 animate-spin" /> : "Save"}
                  </button>
                  <button
                    onClick={() => { setIsEditingTags(false); setEditTags(episode.tags || []); }}
                    className="px-3 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 text-slate-300 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {(episode.tags || []).length > 0 ? (
                  (episode.tags || []).map((tag) => (
                    <span
                      key={tag}
                      className="px-2 py-0.5 text-[10px] rounded-full bg-emerald-900/20 text-emerald-400 border border-emerald-500/20"
                    >
                      {tag}
                    </span>
                  ))
                ) : (
                  <span className="text-[10px] text-slate-500">No tags</span>
                )}
              </div>
            )}
          </div>

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
