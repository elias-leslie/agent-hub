"use client";

import { useState } from "react";
import { X, Pencil, Loader2, Shield, AlertTriangle, BookOpen, Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { MemoryEpisode, MemoryCategory } from "@/lib/memory-api";
import { addEpisode, deleteMemory } from "@/lib/memory-api";
import { CATEGORY_CONFIG } from "@/lib/memory-config";

interface EditEpisodeModalProps {
  episode: MemoryEpisode;
  isOpen: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export function EditEpisodeModal({
  episode,
  isOpen,
  onClose,
  onSaved,
}: EditEpisodeModalProps) {
  const [content, setContent] = useState(episode.content);
  const [tier, setTier] = useState<MemoryCategory>(episode.category);
  const [isTierDropdownOpen, setIsTierDropdownOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tierConfig = CATEGORY_CONFIG[tier];
  const hasChanges = content !== episode.content || tier !== episode.category;

  async function handleSave() {
    if (!hasChanges) {
      onClose();
      return;
    }

    setIsSaving(true);
    setError(null);

    try {
      // Step 1: Create new episode with preserved stats
      const newEpisode = await addEpisode({
        content,
        source: episode.source,
        source_description: episode.source_description,
        injection_tier: tier,
        preserve_stats_from: episode.uuid,
      });

      // Step 2: Delete original episode
      await deleteMemory(episode.uuid);

      // Success - close modal and trigger refresh
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save changes");
    } finally {
      setIsSaving(false);
    }
  }

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      data-testid="edit-episode-modal"
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative w-full max-w-2xl mx-4 rounded-xl bg-white dark:bg-slate-900 shadow-2xl border border-slate-200 dark:border-slate-800">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-full bg-violet-100 dark:bg-violet-900/30">
              <Pencil className="w-5 h-5 text-violet-600 dark:text-violet-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                Edit Memory
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400 font-mono">
                {episode.uuid.slice(0, 8)}...
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isSaving}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-4">
          {/* Tier Selector */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700 dark:text-slate-300">
              Tier
            </label>
            <div className="relative">
              <button
                onClick={() => setIsTierDropdownOpen(!isTierDropdownOpen)}
                disabled={isSaving}
                className={cn(
                  "flex items-center gap-2 w-full px-3 py-2.5 rounded-lg border text-sm font-medium transition-all",
                  tierConfig.bg,
                  "border-slate-200 dark:border-slate-700",
                  "hover:ring-2 hover:ring-offset-1 hover:ring-slate-300 dark:hover:ring-slate-600",
                  "disabled:opacity-50 disabled:cursor-not-allowed"
                )}
              >
                <span className="text-base">{tierConfig.icon}</span>
                <span className={tierConfig.color}>{tierConfig.label}</span>
                <ChevronDown
                  className={cn(
                    "w-4 h-4 ml-auto text-slate-400 transition-transform",
                    isTierDropdownOpen && "rotate-180"
                  )}
                />
              </button>

              {/* Tier Dropdown Menu */}
              {isTierDropdownOpen && (
                <div
                  className="absolute top-full left-0 right-0 mt-1 z-50 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-lg overflow-hidden"
                  onClick={(e) => e.stopPropagation()}
                >
                  {(["mandate", "guardrail", "reference"] as MemoryCategory[]).map((t) => {
                    const config = CATEGORY_CONFIG[t];
                    const isSelected = t === tier;
                    return (
                      <button
                        key={t}
                        onClick={() => {
                          setTier(t);
                          setIsTierDropdownOpen(false);
                        }}
                        className={cn(
                          "w-full flex items-center gap-3 px-3 py-2.5 text-sm font-medium transition-colors",
                          "hover:bg-slate-50 dark:hover:bg-slate-800",
                          isSelected && "bg-slate-100 dark:bg-slate-800"
                        )}
                      >
                        <span className="text-base">{config.icon}</span>
                        <span className={config.color}>{config.label}</span>
                        <span className="text-xs text-slate-400 ml-1">
                          {t === "mandate" && "Always injected"}
                          {t === "guardrail" && "Always injected"}
                          {t === "reference" && "On-demand"}
                        </span>
                        {isSelected && (
                          <Check className="w-4 h-4 ml-auto text-emerald-500" />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {/* Content Editor */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-700 dark:text-slate-300">
              Content
            </label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              disabled={isSaving}
              rows={8}
              className={cn(
                "w-full px-3 py-2.5 rounded-lg text-sm",
                "bg-slate-50 dark:bg-slate-800/50",
                "border border-slate-200 dark:border-slate-700",
                "text-slate-900 dark:text-slate-100",
                "placeholder:text-slate-400",
                "focus:outline-none focus:ring-2 focus:ring-violet-500/50 focus:border-violet-500",
                "disabled:opacity-50 disabled:cursor-not-allowed",
                "resize-none"
              )}
              placeholder="Enter memory content..."
            />
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {content.length} characters
            </p>
          </div>

          {/* Error Message */}
          {error && (
            <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800">
              <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
            </div>
          )}

          {/* Info Box */}
          <div className="p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800">
            <p className="text-xs text-amber-700 dark:text-amber-400">
              <strong>Note:</strong> Editing creates a new memory with the updated content while preserving usage statistics (helpful/harmful counts, load count, etc.).
            </p>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-4 border-t border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30">
          <div className="text-xs text-slate-500">
            {hasChanges ? (
              <span className="text-violet-600 dark:text-violet-400">Unsaved changes</span>
            ) : (
              "No changes"
            )}
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              disabled={isSaving}
              className="px-4 py-2 rounded-lg text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving || !hasChanges || !content.trim()}
              className={cn(
                "px-4 py-2 rounded-lg text-sm font-medium text-white transition-colors flex items-center gap-2",
                "bg-violet-600 hover:bg-violet-700",
                "disabled:opacity-50 disabled:cursor-not-allowed"
              )}
            >
              {isSaving ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Saving...
                </>
              ) : (
                "Save Changes"
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
