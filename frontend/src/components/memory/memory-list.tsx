"use client";

import { useRef, useCallback, useEffect } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Check, Database } from "lucide-react";
import { cn } from "@/lib/utils";
import { MemoryCard } from "./memory-card";
import type { MemoryEpisode } from "@/lib/memory-api";

interface MemoryListProps {
  episodes: MemoryEpisode[];
  isLoading: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
  isFetchingMore: boolean;
  selectedIds: Set<string>;
  onToggleSelect: (id: string) => void;
  onSelectAll: () => void;
  onClearSelection: () => void;
  isAllSelected: boolean;
  onDelete: (id: string) => void;
  isDeleting: boolean;
}

function SkeletonCard() {
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/50 p-4">
      <div className="animate-pulse">
        <div className="flex gap-3">
          <div className="w-5 h-5 rounded bg-slate-200 dark:bg-slate-700" />
          <div className="flex-1 space-y-2">
            <div className="flex gap-2">
              <div className="h-5 w-20 rounded-full bg-slate-200 dark:bg-slate-700" />
              <div className="h-5 w-24 rounded bg-slate-200 dark:bg-slate-700" />
            </div>
            <div className="h-4 w-full rounded bg-slate-200 dark:bg-slate-700" />
            <div className="h-4 w-3/4 rounded bg-slate-200 dark:bg-slate-700" />
          </div>
        </div>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div
      className="flex flex-col items-center justify-center py-16 text-center"
      data-testid="empty-state"
    >
      <div className="p-4 rounded-full bg-slate-100 dark:bg-slate-800 mb-4">
        <Database className="w-8 h-8 text-slate-400 dark:text-slate-500" />
      </div>
      <h3 className="text-lg font-medium text-slate-900 dark:text-slate-100 mb-1">
        No memories found
      </h3>
      <p className="text-sm text-slate-500 dark:text-slate-400 max-w-sm">
        Your agent hasn't stored any memories yet. Memories are created
        automatically during conversations.
      </p>
    </div>
  );
}

export function MemoryList({
  episodes,
  isLoading,
  hasMore,
  onLoadMore,
  isFetchingMore,
  selectedIds,
  onToggleSelect,
  onSelectAll,
  onClearSelection,
  isAllSelected,
  onDelete,
  isDeleting,
}: MemoryListProps) {
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: episodes.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 160, // Estimated card height
    overscan: 5,
  });

  const items = virtualizer.getVirtualItems();

  // Load more when scrolling near bottom
  const handleScroll = useCallback(() => {
    if (!parentRef.current || isFetchingMore || !hasMore) return;

    const { scrollTop, scrollHeight, clientHeight } = parentRef.current;
    const scrollRemaining = scrollHeight - scrollTop - clientHeight;

    // Load more when within 500px of bottom
    if (scrollRemaining < 500) {
      onLoadMore();
    }
  }, [hasMore, isFetchingMore, onLoadMore]);

  useEffect(() => {
    const el = parentRef.current;
    if (!el) return;
    el.addEventListener("scroll", handleScroll);
    return () => el.removeEventListener("scroll", handleScroll);
  }, [handleScroll]);

  if (isLoading) {
    return (
      <div className="space-y-3" data-testid="memory-list-loading">
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  if (episodes.length === 0) {
    return <EmptyState />;
  }

  return (
    <div className="space-y-4" data-testid="memory-list">
      {/* Header with select all */}
      <div className="flex items-center justify-between">
        <button
          onClick={isAllSelected ? onClearSelection : onSelectAll}
          className={cn(
            "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
            isAllSelected
              ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300"
              : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700",
          )}
          data-testid="select-all-checkbox"
        >
          <div
            className={cn(
              "w-4 h-4 rounded border flex items-center justify-center",
              isAllSelected
                ? "bg-emerald-500 border-emerald-500"
                : "border-slate-300 dark:border-slate-600",
            )}
          >
            {isAllSelected && <Check className="w-3 h-3 text-white" />}
          </div>
          {isAllSelected ? "Deselect all" : "Select all"}
        </button>
        <span className="text-sm text-slate-500 dark:text-slate-400">
          {episodes.length} {episodes.length === 1 ? "memory" : "memories"}
        </span>
      </div>

      {/* Virtualized list */}
      <div
        ref={parentRef}
        className="h-[600px] overflow-auto"
        style={{ contain: "strict" }}
      >
        <div
          style={{
            height: `${virtualizer.getTotalSize()}px`,
            width: "100%",
            position: "relative",
          }}
        >
          {items.map((virtualRow) => {
            const episode = episodes[virtualRow.index];
            return (
              <div
                key={virtualRow.key}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: "100%",
                  transform: `translateY(${virtualRow.start}px)`,
                }}
              >
                <div className="pb-3">
                  <MemoryCard
                    episode={episode}
                    isSelected={selectedIds.has(episode.uuid)}
                    onSelect={() => onToggleSelect(episode.uuid)}
                    onDelete={() => onDelete(episode.uuid)}
                    isDeleting={isDeleting}
                  />
                </div>
              </div>
            );
          })}
        </div>

        {/* Loading more indicator */}
        {isFetchingMore && (
          <div className="py-4 text-center">
            <div className="inline-flex items-center gap-2 text-sm text-slate-500">
              <div className="w-4 h-4 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
              Loading more...
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
