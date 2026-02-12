"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchEntityEpisodes } from "@/lib/memory-api";
import type { EntityEpisode, MemoryCategory } from "@/lib/memory-types";
import { CATEGORY_CONFIG } from "@/lib/memory-config";

interface EntityEpisodesListProps {
  entityName: string;
  groupId: string;
}

export function EntityEpisodesList({
  entityName,
  groupId,
}: EntityEpisodesListProps) {
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
