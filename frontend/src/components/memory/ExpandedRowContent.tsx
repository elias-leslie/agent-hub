"use client";

import { useState } from "react";
import { Eye, MessageCircle, ThumbsUp, ThumbsDown, Sparkles, Trash2, ChevronDown, Check, Loader2, Pencil, Tag, X, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import type { MemoryEpisode, MemoryCategory } from "@/lib/memory-api";
import { updateEpisodeTier, updateEpisodeProperties } from "@/lib/memory-api";
import { ScopePill } from "./ScopePill";
import { CopyButton } from "./CopyButton";
import { CATEGORY_CONFIG } from "@/lib/memory-config";
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
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isUpdatingTier, setIsUpdatingTier] = useState(false);
  const [tierError, setTierError] = useState<string | null>(null);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const categoryConfig = CATEGORY_CONFIG[episode.category];

  // Trigger task types state (for reference-tier context-aware injection)
  const [triggerTypes, setTriggerTypes] = useState<string[]>(episode.trigger_task_types || []);
  const [newTriggerType, setNewTriggerType] = useState("");
  const [isUpdatingTriggers, setIsUpdatingTriggers] = useState(false);
  const [triggersError, setTriggersError] = useState<string | null>(null);

  const handleTierChange = async (newTier: MemoryCategory) => {
    if (newTier === episode.category) {
      setIsDropdownOpen(false);
      return;
    }

    setIsUpdatingTier(true);
    setTierError(null);
    try {
      await updateEpisodeTier(episode.uuid, newTier);
      onTierChange?.(newTier);
      setIsDropdownOpen(false);
    } catch (err) {
      setTierError(err instanceof Error ? err.message : "Failed to update tier");
    } finally {
      setIsUpdatingTier(false);
    }
  };

  const handleAddTriggerType = async () => {
    const trimmed = newTriggerType.trim().toLowerCase();
    if (!trimmed || triggerTypes.includes(trimmed)) {
      setNewTriggerType("");
      return;
    }

    const updatedTypes = [...triggerTypes, trimmed];
    setIsUpdatingTriggers(true);
    setTriggersError(null);
    try {
      await updateEpisodeProperties(episode.uuid, { trigger_task_types: updatedTypes });
      setTriggerTypes(updatedTypes);
      setNewTriggerType("");
    } catch (err) {
      setTriggersError(err instanceof Error ? err.message : "Failed to update triggers");
    } finally {
      setIsUpdatingTriggers(false);
    }
  };

  const handleRemoveTriggerType = async (typeToRemove: string) => {
    const updatedTypes = triggerTypes.filter(t => t !== typeToRemove);
    setIsUpdatingTriggers(true);
    setTriggersError(null);
    try {
      await updateEpisodeProperties(episode.uuid, { trigger_task_types: updatedTypes });
      setTriggerTypes(updatedTypes);
    } catch (err) {
      setTriggersError(err instanceof Error ? err.message : "Failed to update triggers");
    } finally {
      setIsUpdatingTriggers(false);
    }
  };

  return (
    <div className="p-5 space-y-5">
      {/* Three-column layout: Content | Stats | Meta */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_200px_220px] gap-5">
        {/* CONTENT PANE */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 flex-wrap">
            <ScopePill scope={episode.scope} size="md" />

            {/* Tier Dropdown */}
            <div className="relative">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setIsDropdownOpen(!isDropdownOpen);
                }}
                disabled={isUpdatingTier}
                className={cn(
                  "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition-all",
                  categoryConfig.bg,
                  categoryConfig.color,
                  "hover:ring-2 hover:ring-offset-1 hover:ring-slate-300 dark:hover:ring-slate-600",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                <span>{categoryConfig.icon}</span>
                <span>{categoryConfig.label}</span>
                {isUpdatingTier ? (
                  <Loader2 className="w-3 h-3 animate-spin ml-0.5" />
                ) : (
                  <ChevronDown className={cn(
                    "w-3 h-3 transition-transform",
                    isDropdownOpen && "rotate-180"
                  )} />
                )}
              </button>

              {/* Dropdown Menu */}
              {isDropdownOpen && (
                <div
                  className="absolute top-full left-0 mt-1 z-50 w-40 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-lg overflow-hidden"
                  onClick={(e) => e.stopPropagation()}
                >
                  {(["mandate", "guardrail", "reference"] as MemoryCategory[]).map((tier) => {
                    const config = CATEGORY_CONFIG[tier];
                    const isSelected = tier === episode.category;
                    return (
                      <button
                        key={tier}
                        onClick={() => handleTierChange(tier)}
                        disabled={isUpdatingTier}
                        className={cn(
                          "w-full flex items-center gap-2 px-3 py-2 text-xs font-medium transition-colors",
                          "hover:bg-slate-50 dark:hover:bg-slate-800",
                          isSelected && "bg-slate-100 dark:bg-slate-800"
                        )}
                      >
                        <span>{config.icon}</span>
                        <span className={config.color}>{config.label}</span>
                        {isSelected && (
                          <Check className="w-3 h-3 ml-auto text-emerald-500" />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <span className="px-2 py-1 rounded text-[10px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 uppercase">
              {episode.source}
            </span>
          </div>

          {/* Tier Error Message */}
          {tierError && (
            <div className="text-xs text-red-500 dark:text-red-400 mt-1">
              {tierError}
            </div>
          )}

          <div className="p-4 rounded-lg bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
            <p className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap leading-relaxed">
              {episode.content}
            </p>
          </div>

          {/* Entity Tags - only show if entities contain human-readable names (not UUIDs) */}
          {episode.entities.length > 0 &&
           episode.entities.some(e => !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(e)) && (
            <div>
              <h4 className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">
                Entities
              </h4>
              <div className="flex flex-wrap gap-1.5">
                {episode.entities
                  .filter(e => !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(e))
                  .map((entity, i) => (
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
            <div>
              <h4 className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2 flex items-center gap-1.5">
                <Tag className="h-3 w-3" />
                Trigger Task Types
              </h4>
              <p className="text-[10px] text-slate-500 dark:text-slate-400 mb-2">
                Auto-inject this reference when task_type matches
              </p>

              {/* Existing trigger types */}
              <div className="flex flex-wrap gap-1.5 mb-2">
                {triggerTypes.map((type) => (
                  <span
                    key={type}
                    className="flex items-center gap-1 px-2 py-1 text-[10px] rounded-full bg-cyan-50 dark:bg-cyan-950/30 text-cyan-700 dark:text-cyan-300 border border-cyan-200 dark:border-cyan-800"
                  >
                    {type}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleRemoveTriggerType(type);
                      }}
                      disabled={isUpdatingTriggers}
                      className="hover:text-cyan-900 dark:hover:text-cyan-100 disabled:opacity-50"
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </span>
                ))}
                {triggerTypes.length === 0 && (
                  <span className="text-[10px] text-slate-400 italic">No triggers set</span>
                )}
              </div>

              {/* Add new trigger type */}
              <div className="flex gap-1.5">
                <input
                  type="text"
                  value={newTriggerType}
                  onChange={(e) => setNewTriggerType(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleAddTriggerType();
                    }
                  }}
                  onClick={(e) => e.stopPropagation()}
                  placeholder="e.g., database, migration"
                  disabled={isUpdatingTriggers}
                  className={cn(
                    "flex-1 px-2 py-1 text-[10px] rounded-md",
                    "bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700",
                    "text-slate-700 dark:text-slate-300 placeholder:text-slate-400",
                    "focus:outline-none focus:ring-1 focus:ring-cyan-500/50",
                    "disabled:opacity-50"
                  )}
                />
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleAddTriggerType();
                  }}
                  disabled={isUpdatingTriggers || !newTriggerType.trim()}
                  className={cn(
                    "px-2 py-1 rounded-md text-[10px] font-medium transition-colors",
                    "bg-cyan-50 dark:bg-cyan-900/20 text-cyan-600 dark:text-cyan-400",
                    "hover:bg-cyan-100 dark:hover:bg-cyan-900/30",
                    "border border-cyan-200 dark:border-cyan-800",
                    "disabled:opacity-50 disabled:cursor-not-allowed"
                  )}
                >
                  {isUpdatingTriggers ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Plus className="h-3 w-3" />
                  )}
                </button>
              </div>

              {/* Error message */}
              {triggersError && (
                <p className="text-[10px] text-red-500 dark:text-red-400 mt-1">{triggersError}</p>
              )}
            </div>
          )}
        </div>

        {/* STATS PANE */}
        <div className="space-y-3">
          <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-400 border-b border-slate-200 dark:border-slate-700 pb-2">
            Usage Stats
          </h4>
          <div className="grid grid-cols-2 gap-2">
            {episode.loaded_count !== undefined && (
              <div className="p-2.5 rounded-lg bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
                <div className="flex items-center gap-1.5 text-slate-500 mb-1">
                  <Eye className="h-3 w-3" />
                  <span className="text-[9px] uppercase tracking-wide font-semibold">Loaded</span>
                </div>
                <p className="text-lg font-bold font-mono tabular-nums text-slate-700 dark:text-slate-200">
                  {episode.loaded_count}
                </p>
              </div>
            )}
            {episode.referenced_count !== undefined && (
              <div className="p-2.5 rounded-lg bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
                <div className="flex items-center gap-1.5 text-slate-500 mb-1">
                  <MessageCircle className="h-3 w-3" />
                  <span className="text-[9px] uppercase tracking-wide font-semibold">Cited</span>
                </div>
                <p className="text-lg font-bold font-mono tabular-nums text-slate-700 dark:text-slate-200">
                  {episode.referenced_count}
                </p>
              </div>
            )}
            {episode.helpful_count !== undefined && (
              <div className={`p-2.5 rounded-lg border ${
                episode.helpful_count > 0
                  ? "bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800"
                  : "bg-white dark:bg-slate-800/50 border-slate-200 dark:border-slate-700"
              }`}>
                <div className={`flex items-center gap-1.5 mb-1 ${
                  episode.helpful_count > 0
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-slate-500"
                }`}>
                  <ThumbsUp className="h-3 w-3" />
                  <span className="text-[9px] uppercase tracking-wide font-semibold">Helpful</span>
                </div>
                <p className={`text-lg font-bold font-mono tabular-nums ${
                  episode.helpful_count > 0
                    ? "text-emerald-700 dark:text-emerald-300"
                    : "text-slate-700 dark:text-slate-200"
                }`}>
                  {episode.helpful_count}
                </p>
              </div>
            )}
            {episode.harmful_count !== undefined && (
              <div className={`p-2.5 rounded-lg border ${
                episode.harmful_count > 0
                  ? "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800"
                  : "bg-white dark:bg-slate-800/50 border-slate-200 dark:border-slate-700"
              }`}>
                <div className={`flex items-center gap-1.5 mb-1 ${
                  episode.harmful_count > 0
                    ? "text-red-600 dark:text-red-400"
                    : "text-slate-500"
                }`}>
                  <ThumbsDown className="h-3 w-3" />
                  <span className="text-[9px] uppercase tracking-wide font-semibold">Harmful</span>
                </div>
                <p className={`text-lg font-bold font-mono tabular-nums ${
                  episode.harmful_count > 0
                    ? "text-red-700 dark:text-red-300"
                    : "text-slate-700 dark:text-slate-200"
                }`}>
                  {episode.harmful_count}
                </p>
              </div>
            )}
            {episode.utility_score !== undefined && (
              <div className="p-2.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800">
                <div className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 mb-1">
                  <Sparkles className="h-3 w-3" />
                  <span className="text-[9px] uppercase tracking-wide font-semibold">Utility</span>
                </div>
                <p className="text-lg font-bold font-mono tabular-nums text-emerald-700 dark:text-emerald-300">
                  {(episode.utility_score * 100).toFixed(0)}%
                </p>
              </div>
            )}
          </div>

          {/* No stats available */}
          {episode.loaded_count === undefined &&
            episode.referenced_count === undefined &&
            episode.helpful_count === undefined &&
            episode.harmful_count === undefined &&
            episode.utility_score === undefined && (
              <p className="text-xs text-slate-400 italic">No usage data yet</p>
            )}
        </div>

        {/* META PANE */}
        <div className="space-y-3">
          <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-400 border-b border-slate-200 dark:border-slate-700 pb-2">
            Metadata
          </h4>
          <div className="space-y-2 text-[11px]">
            <div className="flex justify-between items-center">
              <span className="text-slate-500">ID</span>
              <div className="flex items-center gap-1">
                <code className="font-mono text-slate-600 dark:text-slate-300 truncate max-w-[140px]">
                  {episode.uuid}
                </code>
                <CopyButton text={episode.uuid} />
              </div>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Created</span>
              <span className="font-mono tabular-nums text-slate-600 dark:text-slate-300">
                {new Date(episode.created_at).toLocaleString()}
              </span>
            </div>
            {episode.scope_id && (
              <div className="flex justify-between">
                <span className="text-slate-500">Scope ID</span>
                <code className="font-mono text-slate-600 dark:text-slate-300 truncate max-w-[140px]">
                  {episode.scope_id}
                </code>
              </div>
            )}
          </div>

          {/* Action buttons */}
          <div className="pt-3 border-t border-slate-200 dark:border-slate-700 space-y-2">
            {/* Edit button */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                setIsEditModalOpen(true);
              }}
              className={cn(
                "w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-colors",
                "bg-violet-50 dark:bg-violet-900/20 text-violet-600 dark:text-violet-400",
                "hover:bg-violet-100 dark:hover:bg-violet-900/30",
                "border border-violet-200 dark:border-violet-800"
              )}
            >
              <Pencil className="h-3.5 w-3.5" />
              Edit
            </button>

            {/* Delete button */}
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              disabled={isDeleting}
              className={cn(
                "w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-colors",
                "bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400",
                "hover:bg-red-100 dark:hover:bg-red-900/30",
                "border border-red-200 dark:border-red-800",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {isDeleting ? (
                <div className="w-3.5 h-3.5 border-2 border-red-500 border-t-transparent rounded-full animate-spin" />
              ) : (
                <Trash2 className="h-3.5 w-3.5" />
              )}
              Delete
            </button>
          </div>
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
