"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Check, ChevronDown, Pin } from "lucide-react";
import type { MemoryEpisode, MemoryScope, MemoryCategory } from "@/lib/memory-api";
import { Tooltip } from "./Tooltip";
import { ScopePill } from "./ScopePill";
import { CategoryPill } from "./CategoryPill";
import { RelevanceBadge } from "./RelevanceBadge";
import { ExpandedRowContent } from "./ExpandedRowContent";

interface MemoryTableRowProps {
  item: MemoryEpisode;
  index: number;
  isSelected: boolean;
  isFocused: boolean;
  isExpanded: boolean;
  scope?: MemoryScope;
  category?: MemoryCategory;
  pendingDeleteId: string | null;
  isDeleting: boolean;
  onToggleExpand: (id: string) => void;
  onToggleSelect: (id: string) => void;
  onScopeChange: (scope: MemoryScope | undefined) => void;
  onCategoryChange: (category: MemoryCategory | undefined) => void;
  onDelete: (id: string) => void;
  onTierChange?: (id: string, newCategory: MemoryCategory) => void;
  onEdit?: () => void;
  formatRelativeTime: (date: string) => string;
}

export function MemoryTableRow({
  item,
  isSelected,
  isFocused,
  isExpanded,
  scope,
  category,
  pendingDeleteId,
  isDeleting,
  onToggleExpand,
  onToggleSelect,
  onScopeChange,
  onCategoryChange,
  onDelete,
  onTierChange,
  onEdit,
  formatRelativeTime,
}: MemoryTableRowProps) {
  const hasRelevance = "relevance_score" in item && item.relevance_score !== undefined;
  const [showFullContent, setShowFullContent] = useState(false);
  const CONTENT_LIMIT = 200;
  const isLongContent = item.content.length > CONTENT_LIMIT;
  const displayContent = showFullContent ? item.content : item.content.slice(0, CONTENT_LIMIT);

  const tierBorderColor = {
    mandate: "border-l-red-500 dark:border-l-red-400",
    guardrail: "border-l-amber-500 dark:border-l-amber-400",
    reference: "border-l-blue-500 dark:border-l-blue-400",
  }[item.category] || "";

  return (
    <div key={item.uuid} className={cn("border-l-4", tierBorderColor, isExpanded && "bg-slate-50/50 dark:bg-slate-800/20")}>
      {/* ROW */}
      <button
        onClick={() => onToggleExpand(item.uuid)}
        className={cn(
          "w-full grid grid-cols-[32px_72px_1fr_28px] md:grid-cols-[40px_70px_90px_1fr_80px_70px_32px] gap-2 px-3 py-2.5 items-center text-left transition-colors",
          "hover:bg-slate-50 dark:hover:bg-slate-800/30",
          isFocused && "bg-blue-50 dark:bg-blue-950/20 ring-1 ring-inset ring-blue-200 dark:ring-blue-800",
          isExpanded && "bg-emerald-50/50 dark:bg-emerald-950/10",
          isSelected && !isExpanded && "bg-emerald-50/30 dark:bg-emerald-950/5"
        )}
        data-testid="memory-row"
      >
        {/* Checkbox */}
        <div
          onClick={(e) => {
            e.stopPropagation();
            onToggleSelect(item.uuid);
          }}
          className={cn(
            "w-5 h-5 rounded border flex items-center justify-center transition-colors cursor-pointer",
            isSelected
              ? "bg-emerald-500 border-emerald-500 text-white"
              : "border-slate-300 dark:border-slate-600 hover:border-emerald-400"
          )}
        >
          {isSelected && <Check className="w-3 h-3" />}
        </div>

        {/* Scope - hidden on mobile */}
        <div className="hidden md:block">
          <ScopePill
            scope={item.scope}
            onClick={() => onScopeChange(scope === item.scope ? undefined : item.scope)}
            isActive={scope === item.scope}
          />
        </div>

        {/* Category */}
        <CategoryPill
          category={item.category}
          onClick={() => onCategoryChange(category === item.category ? undefined : item.category)}
          isActive={category === item.category}
        />

        {/* Content */}
        <Tooltip content={item.content.slice(0, 500)} position="bottom">
          <div className="min-w-0 flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              {item.pinned && (
                <Pin className="w-3 h-3 text-violet-500 flex-shrink-0" />
              )}
              <span className="text-xs text-slate-700 dark:text-slate-300 truncate">
                {displayContent}
                {isLongContent && !showFullContent && (
                  <button
                    onClick={(e) => { e.stopPropagation(); setShowFullContent(true); }}
                    className="text-blue-500 hover:text-blue-600 ml-1"
                  >
                    ...more
                  </button>
                )}
                {showFullContent && isLongContent && (
                  <button
                    onClick={(e) => { e.stopPropagation(); setShowFullContent(false); }}
                    className="text-blue-500 hover:text-blue-600 ml-1"
                  >
                    less
                  </button>
                )}
              </span>
              {hasRelevance && <RelevanceBadge score={(item as { relevance_score: number }).relevance_score} />}
            </div>
            {item.summary && (
              <span className="text-[10px] text-slate-500 dark:text-slate-400 truncate font-mono">
                ↳ {item.summary}
              </span>
            )}
          </div>
        </Tooltip>

        {/* Time - hidden on mobile */}
        <div className="hidden md:block text-right">
          <span className="text-[11px] font-mono tabular-nums text-slate-500 dark:text-slate-400">
            {formatRelativeTime(item.created_at)}
          </span>
        </div>

        {/* Utility Score - hidden on mobile */}
        <div className="hidden md:block text-right">
          {item.utility_score !== undefined ? (
            <span
              className={cn(
                "text-[11px] font-mono tabular-nums font-medium",
                item.utility_score >= 0.7
                  ? "text-emerald-600 dark:text-emerald-400"
                  : item.utility_score >= 0.4
                    ? "text-amber-600 dark:text-amber-400"
                    : "text-slate-500 dark:text-slate-400"
              )}
            >
              {(item.utility_score * 100).toFixed(0)}%
            </span>
          ) : (
            <span className="text-[11px] text-slate-400">—</span>
          )}
        </div>

        {/* Expand indicator */}
        <div className="flex items-center justify-end">
          <ChevronDown
            className={cn(
              "h-4 w-4 text-slate-400 transition-transform duration-200",
              isExpanded && "rotate-180"
            )}
          />
        </div>
      </button>

      {/* EXPANDED CONTENT - Accordion animation */}
      <div
        className={cn(
          "grid transition-all duration-300 ease-out",
          isExpanded ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"
        )}
      >
        <div className="overflow-hidden">
          <div className="border-t border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/80">
            <ExpandedRowContent
              episode={item as MemoryEpisode}
              onDelete={() => onDelete(item.uuid)}
              isDeleting={isDeleting && pendingDeleteId === item.uuid}
              onTierChange={onTierChange ? (newCategory) => onTierChange(item.uuid, newCategory) : undefined}
              onEdit={onEdit}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
