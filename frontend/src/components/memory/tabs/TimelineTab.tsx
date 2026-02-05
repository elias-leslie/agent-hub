"use client";

import { useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Clock,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Inbox,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { MemoryCategory, MemoryScope, MemoryEpisode } from "@/lib/memory-api";
import { fetchTimeline, type TimelineGroup } from "@/lib/memory-api";
import { CATEGORY_CONFIG } from "@/lib/memory-config";
import { TimelineItem } from "@/components/memory/TimelineItem";

function TimelineSkeleton() {
  return (
    <div className="p-6 space-y-8 animate-pulse">
      {[1, 2, 3].map((group) => (
        <div key={group} className="space-y-4">
          <div className="flex items-center gap-3">
            <div className="h-5 w-24 bg-slate-800 rounded" />
            <div className="h-5 w-8 bg-slate-800 rounded-full" />
          </div>
          <div className="ml-1.5 space-y-4">
            {[1, 2].map((item) => (
              <div key={item} className="flex gap-4">
                <div className="flex flex-col items-center">
                  <div className="w-3 h-3 rounded-full bg-slate-700 mt-1.5" />
                  <div className="w-px flex-1 bg-slate-800" />
                </div>
                <div className="flex-1 rounded-lg bg-slate-800/50 border border-slate-800 p-3 space-y-2">
                  <div className="flex gap-2">
                    <div className="h-4 w-16 bg-slate-700 rounded" />
                    <div className="h-4 w-12 bg-slate-700 rounded" />
                  </div>
                  <div className="h-4 w-3/4 bg-slate-800 rounded" />
                  <div className="h-4 w-1/2 bg-slate-800 rounded" />
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyTimeline() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="p-4 rounded-full bg-slate-800 mb-4">
        <Inbox className="w-8 h-8 text-slate-500" />
      </div>
      <h3 className="text-lg font-medium text-slate-100 mb-1">
        No episodes yet
      </h3>
      <p className="text-sm text-slate-400 max-w-sm">
        Episodes will appear here grouped by date as they are captured.
      </p>
    </div>
  );
}

function DateGroupHeader({
  label,
  count,
  isOpen,
  onToggle,
}: {
  label: string;
  count: number;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className="flex items-center gap-2 group w-full text-left"
    >
      {isOpen ? (
        <ChevronDown className="h-4 w-4 text-slate-500 group-hover:text-slate-300 transition-colors" />
      ) : (
        <ChevronRight className="h-4 w-4 text-slate-500 group-hover:text-slate-300 transition-colors" />
      )}
      <span className="text-sm font-semibold text-slate-200 group-hover:text-slate-100 transition-colors">
        {label}
      </span>
      <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-slate-800 text-slate-400 border border-slate-700">
        {count}
      </span>
      <div className="flex-1 h-px bg-slate-800 ml-2" />
    </button>
  );
}

function CategoryFilter({
  selected,
  onChange,
}: {
  selected: MemoryCategory | null;
  onChange: (cat: MemoryCategory | null) => void;
}) {
  const categories = Object.entries(CATEGORY_CONFIG) as [
    MemoryCategory,
    (typeof CATEGORY_CONFIG)[MemoryCategory]
  ][];

  return (
    <div className="flex items-center gap-1.5">
      <button
        onClick={() => onChange(null)}
        className={cn(
          "px-2.5 py-1 text-xs rounded-md border transition-colors",
          selected === null
            ? "bg-emerald-500/10 border-emerald-500/40 text-emerald-400"
            : "bg-slate-800 border-slate-700 text-slate-400 hover:text-slate-300 hover:border-slate-600"
        )}
      >
        All
      </button>
      {categories.map(([key, config]) => (
        <button
          key={key}
          onClick={() => onChange(selected === key ? null : key)}
          className={cn(
            "px-2.5 py-1 text-xs rounded-md border transition-colors flex items-center gap-1",
            selected === key
              ? config.bg + " " + config.color
              : "bg-slate-800 border-slate-700 text-slate-400 hover:text-slate-300 hover:border-slate-600"
          )}
        >
          <span className="text-xs leading-none">{config.icon}</span>
          {config.label}
        </button>
      ))}
    </div>
  );
}

export function TimelineTab() {
  const searchParams = useSearchParams();
  const groupId = searchParams.get("group") || "global";
  const scope = (searchParams.get("scope") as MemoryScope) || undefined;

  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [categoryFilter, setCategoryFilter] = useState<MemoryCategory | null>(null);

  const {
    data: groups,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["memoryTimeline", groupId, scope, categoryFilter],
    queryFn: () =>
      fetchTimeline({
        groupId,
        scope,
        category: categoryFilter || undefined,
        limit: 200,
      }),
    staleTime: 30000,
  });

  const toggleGroup = useCallback((dateKey: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(dateKey)) {
        next.delete(dateKey);
      } else {
        next.add(dateKey);
      }
      return next;
    });
  }, []);

  const handleRefresh = useCallback(() => {
    refetch();
  }, [refetch]);

  const totalEpisodes = groups?.reduce((sum, g) => sum + g.count, 0) ?? 0;

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Clock className="h-4 w-4 text-slate-400" />
            <span className="text-sm font-medium text-slate-200">
              Timeline
            </span>
            {!isLoading && (
              <span className="text-xs text-slate-500">
                {totalEpisodes} episodes
              </span>
            )}
          </div>
          <button
            onClick={handleRefresh}
            disabled={isFetching}
            className={cn(
              "p-2 rounded-lg transition-colors",
              "text-slate-400 hover:text-slate-200 hover:bg-slate-800",
              isFetching && "cursor-not-allowed"
            )}
            title="Refresh"
          >
            <RefreshCw
              className={cn(
                "h-4 w-4",
                isFetching && "animate-spin text-emerald-500"
              )}
            />
          </button>
        </div>
        <div className="mt-2.5">
          <CategoryFilter
            selected={categoryFilter}
            onChange={setCategoryFilter}
          />
        </div>
      </div>

      {error && (
        <div className="px-4 py-2 bg-red-900/20 border-b border-red-800">
          <p className="text-sm text-red-400">
            Error: {(error as Error).message}
          </p>
        </div>
      )}

      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <TimelineSkeleton />
        ) : !groups || groups.length === 0 ? (
          <EmptyTimeline />
        ) : (
          <div className="p-4 lg:p-6 space-y-6 max-w-3xl">
            {groups.map((group) => {
              const isOpen = !collapsedGroups.has(group.date_key);
              return (
                <div key={group.date_key}>
                  <DateGroupHeader
                    label={group.label}
                    count={group.count}
                    isOpen={isOpen}
                    onToggle={() => toggleGroup(group.date_key)}
                  />
                  {isOpen && (
                    <div className="mt-3 ml-1">
                      {group.episodes.map(
                        (ep: MemoryEpisode, idx: number) => (
                          <TimelineItem
                            key={ep.uuid}
                            episode={ep}
                            isLast={idx === group.episodes.length - 1}
                          />
                        )
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
