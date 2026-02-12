"use client";

import { AlertTriangle, Trash2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import type { EntityHealthSummary } from "@/lib/memory-types";
import type { CleanupResult } from "@/lib/memory-api";

interface HealthBannerProps {
  health: EntityHealthSummary;
  isCleaningUp: boolean;
  onCleanup: () => void;
  lastResult: CleanupResult | null;
}

export function HealthBanner({
  health,
  isCleaningUp,
  onCleanup,
  lastResult,
}: HealthBannerProps) {
  const hasIssues = health.orphan_count > 0 || health.duplicate_count > 0;
  const totalCleaned = lastResult
    ? lastResult.entities_deleted + lastResult.duplicates_merged + lastResult.edges_deleted
    : 0;

  return (
    <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/60">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-slate-400 font-medium">
            {health.total_entities} entities
          </span>
          <span className="text-xs text-slate-600">|</span>
          <span className="text-xs text-slate-400">
            {health.total_edges} edges
          </span>
          {health.orphan_count > 0 && (
            <span className="flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/30">
              <AlertTriangle className="h-3 w-3" />
              {health.orphan_count} orphans
            </span>
          )}
          {health.duplicate_count > 0 && (
            <span className="flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium rounded-full bg-orange-500/10 text-orange-400 border border-orange-500/30">
              {health.duplicate_count} duplicates
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {lastResult && totalCleaned > 0 && (
            <span className="text-[10px] text-emerald-400">
              Cleaned: {lastResult.entities_deleted > 0 && `${lastResult.entities_deleted} orphans`}
              {lastResult.entities_deleted > 0 && lastResult.duplicates_merged > 0 && ", "}
              {lastResult.duplicates_merged > 0 && `${lastResult.duplicates_merged} dupes merged`}
              {(lastResult.entities_deleted > 0 || lastResult.duplicates_merged > 0) && lastResult.edges_deleted > 0 && ", "}
              {lastResult.edges_deleted > 0 && `${lastResult.edges_deleted} edges`}
            </span>
          )}
          {lastResult && totalCleaned === 0 && (
            <span className="text-[10px] text-slate-500">Nothing to clean</span>
          )}
          {hasIssues && (
            <button
              onClick={onCleanup}
              disabled={isCleaningUp}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors",
                isCleaningUp
                  ? "bg-slate-800 border-slate-700 text-slate-500 cursor-not-allowed"
                  : "bg-red-900/20 border-red-800/40 text-red-400 hover:bg-red-900/30"
              )}
            >
              {isCleaningUp ? (
                <RefreshCw className="h-3 w-3 animate-spin" />
              ) : (
                <Trash2 className="h-3 w-3" />
              )}
              Clean Up
            </button>
          )}
        </div>
      </div>
      {health.duplicate_names.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {health.duplicate_names.map((name) => (
            <span
              key={name}
              className="px-1.5 py-0.5 text-[10px] rounded bg-orange-500/10 text-orange-400 border border-orange-500/20"
            >
              {name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
