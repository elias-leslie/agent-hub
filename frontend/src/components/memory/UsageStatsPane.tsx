"use client";

import { Eye, MessageCircle, ThumbsUp, ThumbsDown, Sparkles, Info } from "lucide-react";
import { Tooltip } from "./Tooltip";

interface UsageStatsPaneProps {
  loadedCount?: number;
  referencedCount?: number;
  helpfulCount?: number;
  harmfulCount?: number;
  utilityScore?: number;
}

export function UsageStatsPane({
  loadedCount,
  referencedCount,
  helpfulCount,
  harmfulCount,
  utilityScore,
}: UsageStatsPaneProps) {
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
            helpfulCount > 0
              ? "bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800"
              : "bg-white dark:bg-slate-800/50 border-slate-200 dark:border-slate-700"
          }`}>
            <div className={`flex items-center gap-1.5 mb-1 ${
              helpfulCount > 0
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-slate-500"
            }`}>
              <ThumbsUp className="h-3 w-3" />
              <span className="text-[9px] uppercase tracking-wide font-semibold">Helpful</span>
            </div>
            <p className={`text-lg font-bold font-mono tabular-nums ${
              helpfulCount > 0
                ? "text-emerald-700 dark:text-emerald-300"
                : "text-slate-700 dark:text-slate-200"
            }`}>
              {helpfulCount}
            </p>
          </div>
        )}
        {harmfulCount !== undefined && (
          <div className={`p-2.5 rounded-lg border ${
            harmfulCount > 0
              ? "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800"
              : "bg-white dark:bg-slate-800/50 border-slate-200 dark:border-slate-700"
          }`}>
            <div className={`flex items-center gap-1.5 mb-1 ${
              harmfulCount > 0
                ? "text-red-600 dark:text-red-400"
                : "text-slate-500"
            }`}>
              <ThumbsDown className="h-3 w-3" />
              <span className="text-[9px] uppercase tracking-wide font-semibold">Harmful</span>
            </div>
            <p className={`text-lg font-bold font-mono tabular-nums ${
              harmfulCount > 0
                ? "text-red-700 dark:text-red-300"
                : "text-slate-700 dark:text-slate-200"
            }`}>
              {harmfulCount}
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

      {/* No stats available */}
      {!hasStats && (
        <p className="text-xs text-slate-400 italic">No usage data yet</p>
      )}
    </div>
  );
}
