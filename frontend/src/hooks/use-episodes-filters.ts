"use client";

import { useState, useMemo, useCallback } from "react";
import type { MemoryEpisode } from "@/lib/memory-api";
import type { SortField, SortDirection } from "@/components/memory/SortableHeader";

interface UseEpisodesFiltersProps {
  displayItems: MemoryEpisode[];
}

export function useEpisodesFilters({ displayItems }: UseEpisodesFiltersProps) {
  const [sortField, setSortField] = useState<SortField>("created_at");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [pinnedOnly, setPinnedOnly] = useState(false);
  const [tagFilter, setTagFilter] = useState<string | null>(null);

  const sortedItems = useMemo(() => {
    let items = pinnedOnly
      ? displayItems.filter((item) => item.pinned)
      : [...displayItems];
    if (tagFilter) {
      items = items.filter((item) => item.tags?.includes(tagFilter));
    }
    items.sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "scope":
          cmp = (a.scope || "").localeCompare(b.scope || "");
          break;
        case "category":
          cmp = (a.category || "").localeCompare(b.category || "");
          break;
        case "content":
          cmp = (a.summary || "").localeCompare(b.summary || "");
          break;
        case "created_at":
          cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
          break;
        case "utility":
          cmp = (a.utility_score || 0) - (b.utility_score || 0);
          break;
      }
      return sortDirection === "asc" ? cmp : -cmp;
    });
    return items;
  }, [displayItems, sortField, sortDirection, pinnedOnly, tagFilter]);

  return {
    sortField,
    setSortField,
    sortDirection,
    setSortDirection,
    pinnedOnly,
    setPinnedOnly,
    tagFilter,
    setTagFilter,
    sortedItems,
  };
}
