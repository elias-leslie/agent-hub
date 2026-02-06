"use client";

import { Pencil, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { CopyButton } from "./CopyButton";
import type { MemoryEpisode } from "@/lib/memory-api";

interface MetadataPaneProps {
  episode: MemoryEpisode;
  onEdit: () => void;
  onDelete: () => void;
  isDeleting: boolean;
}

export function MetadataPane({ episode, onEdit, onDelete, isDeleting }: MetadataPaneProps) {
  return (
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
        {episode.summary && (
          <div className="flex justify-between items-start">
            <span className="text-slate-500">Summary</span>
            <span className="font-mono text-cyan-600 dark:text-cyan-400 text-right max-w-[140px]">
              {episode.summary}
            </span>
          </div>
        )}
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
            onEdit();
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
  );
}
