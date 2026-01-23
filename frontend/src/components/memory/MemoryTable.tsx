"use client";

import { cn } from "@/lib/utils";
import { Check, Database } from "lucide-react";
import type { MemoryEpisode, MemoryScope, MemoryCategory } from "@/lib/memory-api";
import { SortableHeader, type SortField, type SortDirection } from "./SortableHeader";
import { MemoryTableRow } from "./MemoryTableRow";

interface MemoryTableProps {
  items: MemoryEpisode[];
  isLoading: boolean;
  isFetchingMore: boolean;
  isSearchMode: boolean;
  searchQuery: string;
  sortField: SortField;
  sortDirection: SortDirection;
  selectedIds: Set<string>;
  isAllSelected: boolean;
  focusedRowIndex: number;
  expandedMemoryId: string | null;
  scope?: MemoryScope;
  category?: MemoryCategory;
  pendingDeleteId: string | null;
  isDeleting: boolean;
  onSort: (field: SortField) => void;
  onSelectAll: () => void;
  onClearSelection: () => void;
  onToggleExpand: (id: string) => void;
  onToggleSelect: (id: string) => void;
  onScopeChange: (scope: MemoryScope | undefined) => void;
  onCategoryChange: (category: MemoryCategory | undefined) => void;
  onDelete: (id: string) => void;
  formatRelativeTime: (date: string) => string;
}

export function MemoryTable({
  items,
  isLoading,
  isFetchingMore,
  isSearchMode,
  searchQuery,
  sortField,
  sortDirection,
  selectedIds,
  isAllSelected,
  focusedRowIndex,
  expandedMemoryId,
  scope,
  category,
  pendingDeleteId,
  isDeleting,
  onSort,
  onSelectAll,
  onClearSelection,
  onToggleExpand,
  onToggleSelect,
  onScopeChange,
  onCategoryChange,
  onDelete,
  formatRelativeTime,
}: MemoryTableProps) {
  return (
    <>
      {/* Table Header */}
      <div className="sticky top-0 z-10 bg-slate-50/95 dark:bg-slate-800/95 backdrop-blur-sm border-b border-slate-200 dark:border-slate-700">
        <div className="grid grid-cols-[40px_70px_90px_1fr_80px_70px_32px] gap-2 px-3 py-2 items-center">
          <button
            onClick={isAllSelected ? onClearSelection : onSelectAll}
            className={cn(
              "w-5 h-5 rounded border flex items-center justify-center transition-colors",
              isAllSelected
                ? "bg-emerald-500 border-emerald-500 text-white"
                : "border-slate-300 dark:border-slate-600 hover:border-emerald-400"
            )}
            data-testid="select-all-checkbox"
          >
            {isAllSelected && <Check className="w-3 h-3" />}
          </button>

          <SortableHeader label="Scope" field="scope" currentField={sortField} direction={sortDirection} onSort={onSort} />
          <SortableHeader label="Category" field="category" currentField={sortField} direction={sortDirection} onSort={onSort} />
          <SortableHeader label="Content" field="content" currentField={sortField} direction={sortDirection} onSort={onSort} />
          <SortableHeader label="Time" field="created_at" currentField={sortField} direction={sortDirection} onSort={onSort} align="right" />
          <SortableHeader label="Utility" field="utility" currentField={sortField} direction={sortDirection} onSort={onSort} align="right" />
          <div />
        </div>
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="divide-y divide-slate-100 dark:divide-slate-800/50">
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="grid grid-cols-[40px_70px_90px_1fr_80px_70px_32px] gap-2 px-3 py-2.5 items-center">
              <div className="h-4 w-4 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              <div className="h-5 w-14 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              <div className="h-5 w-16 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              <div className="h-4 w-full max-w-md rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              <div className="h-4 w-12 rounded bg-slate-200 dark:bg-slate-700 animate-pulse ml-auto" />
              <div className="h-4 w-10 rounded bg-slate-200 dark:bg-slate-700 animate-pulse ml-auto" />
              <div className="h-4 w-4 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
            </div>
          ))}
        </div>
      )}

      {/* Empty State */}
      {!isLoading && items.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="p-4 rounded-full bg-slate-100 dark:bg-slate-800 mb-4">
            <Database className="w-8 h-8 text-slate-400" />
          </div>
          <h3 className="text-lg font-medium text-slate-900 dark:text-slate-100 mb-1">
            No memories found
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 max-w-sm">
            {isSearchMode
              ? `No results for "${searchQuery}"`
              : "Memories will appear here as they are created"}
          </p>
        </div>
      )}

      {/* Table Rows */}
      {!isLoading && items.length > 0 && (
        <div className="divide-y divide-slate-100 dark:divide-slate-800/50">
          {items.map((item, index) => (
            <MemoryTableRow
              key={item.uuid}
              item={item}
              index={index}
              isSelected={selectedIds.has(item.uuid)}
              isFocused={focusedRowIndex === index}
              isExpanded={expandedMemoryId === item.uuid}
              scope={scope}
              category={category}
              pendingDeleteId={pendingDeleteId}
              isDeleting={isDeleting}
              onToggleExpand={onToggleExpand}
              onToggleSelect={onToggleSelect}
              onScopeChange={onScopeChange}
              onCategoryChange={onCategoryChange}
              onDelete={onDelete}
              formatRelativeTime={formatRelativeTime}
            />
          ))}

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
      )}
    </>
  );
}
