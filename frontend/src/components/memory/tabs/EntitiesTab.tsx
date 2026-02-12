"use client";

import { useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import {
  fetchEntities,
  fetchEntityHealth,
  runMemoryCleanup,
} from "@/lib/memory-api";
import { HealthBanner } from "./HealthBanner";
import { EntityRow } from "./EntityRow";

export function EntitiesTab() {
  const searchParams = useSearchParams();
  const groupId = searchParams.get("group") || "global";
  const queryClient = useQueryClient();

  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [expandedEntity, setExpandedEntity] = useState<string | null>(null);
  const [debounceTimer, setDebounceTimer] = useState<ReturnType<typeof setTimeout> | null>(null);

  const handleSearchChange = useCallback(
    (value: string) => {
      setSearch(value);
      if (debounceTimer) clearTimeout(debounceTimer);
      const timer = setTimeout(() => setDebouncedSearch(value), 300);
      setDebounceTimer(timer);
    },
    [debounceTimer]
  );

  const {
    data: entityList,
    isLoading: isLoadingEntities,
  } = useQuery({
    queryKey: ["entityList", groupId, debouncedSearch],
    queryFn: () =>
      fetchEntities({ groupId, search: debouncedSearch || undefined }),
  });

  const { data: health } = useQuery({
    queryKey: ["entityHealth", groupId],
    queryFn: () => fetchEntityHealth(groupId),
    staleTime: 60000,
  });

  const cleanupMutation = useMutation({
    mutationFn: runMemoryCleanup,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["entityHealth"] });
      queryClient.invalidateQueries({ queryKey: ["entityList"] });
    },
  });

  const duplicateNames = new Set(health?.duplicate_names ?? []);

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {health && (
        <HealthBanner
          health={health}
          isCleaningUp={cleanupMutation.isPending}
          onCleanup={() => cleanupMutation.mutate()}
          lastResult={cleanupMutation.data ?? null}
        />
      )}

      <div className="px-4 py-3 border-b border-slate-800 bg-slate-900/80">
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <input
              type="text"
              placeholder="Search entities..."
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="w-full pl-9 pr-9 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 focus:border-emerald-500"
            />
            {search && (
              <button
                onClick={() => {
                  setSearch("");
                  setDebouncedSearch("");
                }}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
          {entityList && (
            <span className="text-xs text-slate-400">
              {entityList.entities.length} of {entityList.total}
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        {isLoadingEntities ? (
          <div className="p-4 space-y-2 animate-pulse">
            {Array.from({ length: 10 }).map((_, i) => (
              <div key={i} className="h-10 bg-slate-800 rounded" />
            ))}
          </div>
        ) : !entityList || entityList.entities.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24 text-center">
            <h3 className="text-lg font-medium text-slate-100 mb-1">
              No entities found
            </h3>
            <p className="text-sm text-slate-400 max-w-sm">
              {debouncedSearch
                ? `No entities matching "${debouncedSearch}"`
                : "Entities are extracted from episodes by Graphiti."}
            </p>
          </div>
        ) : (
          <div>
            {entityList.entities.map((entity) => (
              <EntityRow
                key={entity.uuid}
                entity={entity}
                groupId={groupId}
                isExpanded={expandedEntity === entity.uuid}
                onToggle={() =>
                  setExpandedEntity((prev) =>
                    prev === entity.uuid ? null : entity.uuid
                  )
                }
                isOrphan={entity.episode_count === 0}
                isDuplicate={duplicateNames.has(entity.name)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
