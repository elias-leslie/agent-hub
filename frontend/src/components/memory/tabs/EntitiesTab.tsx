"use client";

import { useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Search,
  X,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Trash2,
  RefreshCw,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchEntities,
  fetchEntityHealth,
  fetchEntityEpisodes,
  cleanupOrphanedEdges,
} from "@/lib/memory-api";
import type {
  EntitySummary,
  EntityEpisode,
  EntityHealthSummary,
} from "@/lib/memory-types";
import { CATEGORY_CONFIG } from "@/lib/memory-config";
import type { MemoryCategory } from "@/lib/memory-types";

function HealthBanner({
  health,
  isCleaningUp,
  onCleanup,
}: {
  health: EntityHealthSummary;
  isCleaningUp: boolean;
  onCleanup: () => void;
}) {
  const hasIssues = health.orphan_count > 0 || health.duplicate_count > 0;

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

function EntityEpisodesList({
  entityName,
  groupId,
}: {
  entityName: string;
  groupId: string;
}) {
  const { data: episodes, isLoading } = useQuery({
    queryKey: ["entityEpisodes", entityName, groupId],
    queryFn: () => fetchEntityEpisodes(entityName, groupId),
  });

  if (isLoading) {
    return (
      <div className="py-2 px-3 space-y-2 animate-pulse">
        {[1, 2].map((i) => (
          <div key={i} className="h-10 bg-slate-800 rounded" />
        ))}
      </div>
    );
  }

  if (!episodes || episodes.length === 0) {
    return (
      <p className="py-2 px-3 text-xs text-slate-500">No connected episodes</p>
    );
  }

  return (
    <div className="py-2 px-3 space-y-1.5">
      {episodes.map((ep: EntityEpisode) => {
        const tierConfig = ep.injection_tier
          ? CATEGORY_CONFIG[ep.injection_tier as MemoryCategory]
          : null;
        return (
          <div
            key={ep.uuid}
            className="flex items-start gap-2 p-2 rounded border border-slate-800 bg-slate-800/30"
          >
            {tierConfig && (
              <span className="text-xs shrink-0 mt-0.5">{tierConfig.icon}</span>
            )}
            <div className="min-w-0 flex-1">
              <p className="text-xs text-slate-300 break-words leading-relaxed">
                {ep.content}
              </p>
              <span className="text-[10px] text-slate-500">
                {ep.created_at
                  ? new Date(ep.created_at).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                    })
                  : "unknown"}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function EntityRow({
  entity,
  groupId,
  isExpanded,
  onToggle,
  isOrphan,
  isDuplicate,
}: {
  entity: EntitySummary;
  groupId: string;
  isExpanded: boolean;
  onToggle: () => void;
  isOrphan: boolean;
  isDuplicate: boolean;
}) {
  return (
    <div className="border-b border-slate-800/50">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-slate-800/40 transition-colors"
      >
        {isExpanded ? (
          <ChevronDown className="h-3.5 w-3.5 text-slate-500 shrink-0" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-slate-500 shrink-0" />
        )}
        <span className="text-sm text-slate-200 font-medium truncate flex-1 min-w-0">
          {entity.name}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          {isOrphan && (
            <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-amber-500/10 text-amber-400 border border-amber-500/30">
              orphan
            </span>
          )}
          {isDuplicate && (
            <span className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-orange-500/10 text-orange-400 border border-orange-500/30">
              duplicate
            </span>
          )}
          <span className="px-1.5 py-0.5 text-[10px] font-medium rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/30">
            {entity.episode_count} ep
          </span>
          <span className="px-1.5 py-0.5 text-[10px] font-medium rounded-full bg-slate-700 text-slate-400 border border-slate-600">
            {entity.edge_count} edges
          </span>
          {entity.created_at && (
            <span className="text-[10px] text-slate-500 tabular-nums">
              {new Date(entity.created_at).toLocaleDateString("en-US", {
                month: "short",
                day: "numeric",
              })}
            </span>
          )}
        </div>
      </button>
      {isExpanded && (
        <div className="bg-slate-900/40 border-t border-slate-800/50">
          <EntityEpisodesList entityName={entity.name} groupId={groupId} />
        </div>
      )}
    </div>
  );
}

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
    mutationFn: cleanupOrphanedEdges,
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
