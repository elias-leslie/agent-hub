"use client";

import { Eye, MessageCircle, ThumbsUp, Sparkles, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { MemoryEpisode } from "@/lib/memory-api";
import { ScopePill } from "./ScopePill";
import { CategoryPill, CATEGORY_CONFIG } from "./CategoryPill";
import { CopyButton } from "./CopyButton";

export function ExpandedRowContent({
  episode,
  onDelete,
  isDeleting,
}: {
  episode: MemoryEpisode;
  onDelete: () => void;
  isDeleting: boolean;
}) {
  const categoryConfig = CATEGORY_CONFIG[episode.category];

  return (
    <div className="p-5 space-y-5">
      {/* Three-column layout: Content | Stats | Meta */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_200px_220px] gap-5">
        {/* CONTENT PANE */}
        <div className="space-y-4">
          <div className="flex items-center gap-2 flex-wrap">
            <ScopePill scope={episode.scope} size="md" />
            <CategoryPill category={episode.category} size="md" />
            <span className="px-2 py-1 rounded text-[10px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 uppercase">
              {episode.source}
            </span>
          </div>

          <div className="p-4 rounded-lg bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
            <p className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap leading-relaxed">
              {episode.content}
            </p>
          </div>

          {/* Entity Tags */}
          {episode.entities.length > 0 && (
            <div>
              <h4 className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">
                Entities
              </h4>
              <div className="flex flex-wrap gap-1.5">
                {episode.entities.map((entity, i) => (
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
            {episode.success_count !== undefined && (
              <div className="p-2.5 rounded-lg bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
                <div className="flex items-center gap-1.5 text-slate-500 mb-1">
                  <ThumbsUp className="h-3 w-3" />
                  <span className="text-[9px] uppercase tracking-wide font-semibold">Success</span>
                </div>
                <p className="text-lg font-bold font-mono tabular-nums text-slate-700 dark:text-slate-200">
                  {episode.success_count}
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
            episode.success_count === undefined &&
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

          {/* Delete button */}
          <div className="pt-3 border-t border-slate-200 dark:border-slate-700">
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
    </div>
  );
}
