"use client";

import { useCallback, useEffect, useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  fetchMemoryStats,
  fetchMemoryList,
  fetchMemoryGroups,
  searchMemories,
  deleteMemory,
  bulkDeleteMemories,
  exportMemoriesAsJson,
  downloadJson,
  type MemoryCategory,
  type MemoryEpisode,
  type MemoryStats,
  type MemoryGroup,
  type MemoryListResult,
  type SearchResponse,
} from "@/lib/memory-api";

export interface UseMemoryOptions {
  groupId?: string;
  category?: MemoryCategory;
  limit?: number;
}

export interface UseMemoryReturn {
  // Data
  stats: MemoryStats | undefined;
  groups: MemoryGroup[];
  episodes: MemoryEpisode[];
  searchResults: SearchResponse | undefined;

  // Pagination
  hasMore: boolean;
  loadMore: () => void;
  isFetchingMore: boolean;

  // Loading states
  isLoadingStats: boolean;
  isLoadingGroups: boolean;
  isLoadingEpisodes: boolean;
  isSearching: boolean;

  // Errors
  statsError: Error | null;
  episodesError: Error | null;

  // Selection
  selectedIds: Set<string>;
  toggleSelect: (id: string) => void;
  selectAll: () => void;
  clearSelection: () => void;
  isAllSelected: boolean;

  // Search
  searchQuery: string;
  setSearchQuery: (query: string) => void;

  // Actions
  deleteOne: (id: string) => Promise<void>;
  deleteSelected: () => Promise<void>;
  exportSelected: () => void;
  isDeleting: boolean;

  // Refresh
  refresh: () => void;
}

export function useMemory(options: UseMemoryOptions = {}): UseMemoryReturn {
  const { groupId, category, limit = 50 } = options;
  const queryClient = useQueryClient();

  // Selection state
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState("");

  // Debounce search query (500ms)
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearchQuery(searchQuery);
    }, 500);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  // Fetch stats
  const {
    data: stats,
    isLoading: isLoadingStats,
    error: statsError,
  } = useQuery({
    queryKey: ["memoryStats", groupId],
    queryFn: () => fetchMemoryStats(groupId),
    refetchInterval: 60000, // Refresh every minute
  });

  // Fetch groups
  const { data: groupsData, isLoading: isLoadingGroups } = useQuery({
    queryKey: ["memoryGroups"],
    queryFn: fetchMemoryGroups,
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  });

  // Fetch episodes with infinite query for virtual scrolling
  const {
    data: episodesData,
    isLoading: isLoadingEpisodes,
    error: episodesError,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["memoryList", groupId, category, limit],
    queryFn: ({ pageParam }) =>
      fetchMemoryList({
        limit,
        cursor: pageParam as string | undefined,
        category,
        groupId,
      }),
    getNextPageParam: (lastPage: MemoryListResult) =>
      lastPage.has_more ? lastPage.cursor : undefined,
    initialPageParam: undefined as string | undefined,
  });

  // Search query (uses debounced value)
  const {
    data: searchResults,
    isLoading: isSearching,
    isFetching: isSearchFetching,
  } = useQuery({
    queryKey: ["memorySearch", debouncedSearchQuery, groupId],
    queryFn: () => searchMemories(debouncedSearchQuery, { groupId }),
    enabled: debouncedSearchQuery.length >= 2, // Only search with 2+ chars
    staleTime: 30000, // Cache search results for 30s
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: ({ id }: { id: string }) => deleteMemory(id, groupId),
    onSuccess: () => {
      // Invalidate queries to refresh data
      queryClient.invalidateQueries({ queryKey: ["memoryList"] });
      queryClient.invalidateQueries({ queryKey: ["memoryStats"] });
    },
  });

  // Bulk delete mutation
  const bulkDeleteMutation = useMutation({
    mutationFn: ({ ids }: { ids: string[] }) =>
      bulkDeleteMemories(ids, groupId),
    onSuccess: () => {
      setSelectedIds(new Set());
      queryClient.invalidateQueries({ queryKey: ["memoryList"] });
      queryClient.invalidateQueries({ queryKey: ["memoryStats"] });
    },
  });

  // Flatten episodes from infinite query pages
  const episodes =
    episodesData?.pages.flatMap((page) => page.episodes) ?? [];

  // Selection handlers
  const toggleSelect = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(episodes.map((ep) => ep.uuid)));
  }, [episodes]);

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const isAllSelected =
    episodes.length > 0 && selectedIds.size === episodes.length;

  // Delete handlers
  const deleteOne = useCallback(
    async (id: string) => {
      await deleteMutation.mutateAsync({ id });
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    },
    [deleteMutation],
  );

  const deleteSelected = useCallback(async () => {
    if (selectedIds.size === 0) return;
    await bulkDeleteMutation.mutateAsync({ ids: Array.from(selectedIds) });
  }, [selectedIds, bulkDeleteMutation]);

  // Export handler
  const exportSelected = useCallback(() => {
    const selectedEpisodes = episodes.filter((ep) =>
      selectedIds.has(ep.uuid),
    );
    if (selectedEpisodes.length === 0) return;

    const blob = exportMemoriesAsJson(selectedEpisodes);
    const filename = `memories-export-${new Date().toISOString().split("T")[0]}.json`;
    downloadJson(blob, filename);
  }, [episodes, selectedIds]);

  // Refresh handler
  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["memoryList"] });
    queryClient.invalidateQueries({ queryKey: ["memoryStats"] });
    queryClient.invalidateQueries({ queryKey: ["memoryGroups"] });
  }, [queryClient]);

  return {
    // Data
    stats,
    groups: groupsData ?? [],
    episodes,
    searchResults,

    // Pagination
    hasMore: hasNextPage ?? false,
    loadMore: () => fetchNextPage(),
    isFetchingMore: isFetchingNextPage,

    // Loading states
    isLoadingStats,
    isLoadingGroups,
    isLoadingEpisodes,
    isSearching: isSearching || isSearchFetching || (searchQuery.length >= 2 && searchQuery !== debouncedSearchQuery),

    // Errors
    statsError: statsError as Error | null,
    episodesError: episodesError as Error | null,

    // Selection
    selectedIds,
    toggleSelect,
    selectAll,
    clearSelection,
    isAllSelected,

    // Search
    searchQuery,
    setSearchQuery,

    // Actions
    deleteOne,
    deleteSelected,
    exportSelected,
    isDeleting: deleteMutation.isPending || bulkDeleteMutation.isPending,

    // Refresh
    refresh,
  };
}
