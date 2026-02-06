"use client";

import { useState } from "react";
import { Eye, MessageCircle, ThumbsUp, ThumbsDown, Sparkles, Loader2, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { Tooltip } from "./Tooltip";
import { rateEpisode } from "@/lib/memory-api";

interface UsageStatsPaneProps {
  episodeUuid: string;
  loadedCount?: number;
  referencedCount?: number;
  helpfulCount?: number;
  harmfulCount?: number;
  utilityScore?: number;
}

export function UsageStatsPane({
  episodeUuid,
  loadedCount,
  referencedCount,
  helpfulCount,
  harmfulCount,
  utilityScore,
}: UsageStatsPaneProps) {
  const [isRating, setIsRating] = useState(false);
  const [ratingError, setRatingError] = useState<string | null>(null);
  const [localHelpful, setLocalHelpful] = useState(helpfulCount ?? 0);
  const [localHarmful, setLocalHarmful] = useState(harmfulCount ?? 0);

  const handleRate = async (rating: "helpful" | "harmful") => {
    setIsRating(true);
    setRatingError(null);
    try {
      await rateEpisode(episodeUuid, rating);
      if (rating === "helpful") {
        setLocalHelpful(prev => prev + 1);
      } else {
        setLocalHarmful(prev => prev + 1);
      }
    } catch (err) {
      setRatingError(err instanceof Error ? err.message : "Failed to rate");
    } finally {
      setIsRating(false);
    }
  };

  const hasStats = loadedCount !== undefined ||
    referencedCount !== undefined ||
    helpfulCount !== undefined ||
    harmfulCount !== undefined ||
    utilityScore !== undefined;

  return (
    <div className="space-y-3">
      <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-400 border-b border-slate-200 dark:border-slate-700 pb-2">
        Usage Stats
      </h4>
      <div className="grid grid-cols-2 gap-2">
        {loadedCount !== undefined && (
          <div className="p-2.5 rounded-lg bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
            <div className="flex items-center gap-1.5 text-slate-500 mb-1">
              <Eye className="h-3 w-3" />
              <span className="text-[9px] uppercase tracking-wide font-semibold">Loaded</span>
            </div>
            <p className="text-lg font-bold font-mono tabular-nums text-slate-700 dark:text-slate-200">
              {loadedCount}
            </p>
          </div>
        )}
        {referencedCount !== undefined && (
          <div className="p-2.5 rounded-lg bg-white dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
            <div className="flex items-center gap-1.5 text-slate-500 mb-1">
              <MessageCircle className="h-3 w-3" />
              <span className="text-[9px] uppercase tracking-wide font-semibold">Cited</span>
            </div>
            <p className="text-lg font-bold font-mono tabular-nums text-slate-700 dark:text-slate-200">
              {referencedCount}
            </p>
          </div>
        )}
        {helpfulCount !== undefined && (
          <div className={`p-2.5 rounded-lg border ${
            localHelpful > 0
              ? "bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800"
              : "bg-white dark:bg-slate-800/50 border-slate-200 dark:border-slate-700"
          }`}>
            <div className={`flex items-center gap-1.5 mb-1 ${
              localHelpful > 0
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-slate-500"
            }`}>
              <ThumbsUp className="h-3 w-3" />
              <span className="text-[9px] uppercase tracking-wide font-semibold">Helpful</span>
            </div>
            <p className={`text-lg font-bold font-mono tabular-nums ${
              localHelpful > 0
                ? "text-emerald-700 dark:text-emerald-300"
                : "text-slate-700 dark:text-slate-200"
            }`}>
              {localHelpful}
            </p>
          </div>
        )}
        {harmfulCount !== undefined && (
          <div className={`p-2.5 rounded-lg border ${
            localHarmful > 0
              ? "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800"
              : "bg-white dark:bg-slate-800/50 border-slate-200 dark:border-slate-700"
          }`}>
            <div className={`flex items-center gap-1.5 mb-1 ${
              localHarmful > 0
                ? "text-red-600 dark:text-red-400"
                : "text-slate-500"
            }`}>
              <ThumbsDown className="h-3 w-3" />
              <span className="text-[9px] uppercase tracking-wide font-semibold">Harmful</span>
            </div>
            <p className={`text-lg font-bold font-mono tabular-nums ${
              localHarmful > 0
                ? "text-red-700 dark:text-red-300"
                : "text-slate-700 dark:text-slate-200"
            }`}>
              {localHarmful}
            </p>
          </div>
        )}
        {utilityScore !== undefined && (
          <div className="p-2.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800">
            <div className="flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400 mb-1">
              <Sparkles className="h-3 w-3" />
              <span className="text-[9px] uppercase tracking-wide font-semibold">Utility</span>
              <Tooltip content="Utility = helpful / (helpful + harmful) ratio">
                <Info className="h-2.5 w-2.5 opacity-50 cursor-help" />
              </Tooltip>
            </div>
            <p className="text-lg font-bold font-mono tabular-nums text-emerald-700 dark:text-emerald-300">
              {(utilityScore * 100).toFixed(0)}%
            </p>
          </div>
        )}
      </div>

      {/* Rate buttons */}
      <div className="flex gap-2 pt-1">
        <button
          onClick={(e) => { e.stopPropagation(); handleRate("helpful"); }}
          disabled={isRating}
          className={cn(
            "flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md text-xs font-medium border transition-colors",
            "bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 dark:text-emerald-400",
            "hover:bg-emerald-100 dark:hover:bg-emerald-900/30",
            "border-emerald-200 dark:border-emerald-800",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          {isRating ? <Loader2 className="h-3 w-3 animate-spin" /> : <ThumbsUp className="h-3 w-3" />}
          Helpful
        </button>
        <button
          onClick={(e) => { e.stopPropagation(); handleRate("harmful"); }}
          disabled={isRating}
          className={cn(
            "flex-1 flex items-center justify-center gap-1.5 px-2 py-1.5 rounded-md text-xs font-medium border transition-colors",
            "bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400",
            "hover:bg-red-100 dark:hover:bg-red-900/30",
            "border-red-200 dark:border-red-800",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          {isRating ? <Loader2 className="h-3 w-3 animate-spin" /> : <ThumbsDown className="h-3 w-3" />}
          Harmful
        </button>
      </div>
      {ratingError && (
        <p className="text-[10px] text-red-500 dark:text-red-400">{ratingError}</p>
      )}

      {/* No stats available */}
      {!hasStats && (
        <p className="text-xs text-slate-400 italic">No usage data yet</p>
      )}
    </div>
  );
}
