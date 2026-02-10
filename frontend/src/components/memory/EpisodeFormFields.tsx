"use client";

import { FileText, Pin } from "lucide-react";
import { cn } from "@/lib/utils";

interface EpisodeFormFieldsProps {
  summary: string;
  onSummaryChange: (value: string) => void;
  pinned: boolean;
  onPinnedChange: (value: boolean) => void;
  content: string;
  onContentChange: (value: string) => void;
  episodeUuid: string;
  disabled?: boolean;
}

export function EpisodeFormFields({
  summary,
  onSummaryChange,
  pinned,
  onPinnedChange,
  content,
  onContentChange,
  episodeUuid,
  disabled,
}: EpisodeFormFieldsProps) {
  return (
    <>
      {/* Summary Field */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-700 dark:text-slate-300 flex items-center gap-2">
          <FileText className="w-4 h-4 text-cyan-500" />
          Summary
          <span className="text-xs font-normal text-slate-400">(for TOON index)</span>
        </label>
        <input
          type="text"
          value={summary}
          onChange={(e) => onSummaryChange(e.target.value)}
          disabled={disabled}
          maxLength={50}
          className={cn(
            "w-full px-3 py-2.5 rounded-lg text-sm font-mono",
            "bg-slate-50 dark:bg-slate-800/50",
            "border border-slate-200 dark:border-slate-700",
            "text-slate-900 dark:text-slate-100",
            "placeholder:text-slate-400",
            "focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
          placeholder="e.g., use dt for tests"
        />
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Short action phrase (~20 chars) shown in reference index:{" "}
          <code className="text-cyan-600 dark:text-cyan-400">
            {episodeUuid.slice(0, 8)}:{summary || "..."}
          </code>
        </p>
      </div>

      {/* Pinned Toggle */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Always Show</label>
        <button
          type="button"
          onClick={() => onPinnedChange(!pinned)}
          disabled={disabled}
          className={cn(
            "flex items-center gap-3 w-full px-3 py-2.5 rounded-lg border text-sm transition-all",
            pinned
              ? "border-violet-300 dark:border-violet-700 bg-violet-50 dark:bg-violet-900/20"
              : "border-slate-200 dark:border-slate-700",
            "hover:ring-2 hover:ring-offset-1 hover:ring-slate-300 dark:hover:ring-slate-600",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          <Pin className={cn("w-4 h-4", pinned ? "text-violet-600 dark:text-violet-400" : "text-slate-400")} />
          <span className={pinned ? "text-violet-700 dark:text-violet-300 font-medium" : "text-slate-600 dark:text-slate-400"}>
            {pinned ? "Pinned (always injected)" : "Not pinned"}
          </span>
        </button>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Pinned episodes are always included in context, regardless of budget limits.
        </p>
      </div>

      {/* Content Editor */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-700 dark:text-slate-300">Content</label>
        <textarea
          value={content}
          onChange={(e) => onContentChange(e.target.value)}
          disabled={disabled}
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
        <p className="text-xs text-slate-500 dark:text-slate-400">{content.length} characters</p>
      </div>
    </>
  );
}
