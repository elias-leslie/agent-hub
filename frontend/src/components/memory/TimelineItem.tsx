"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { MemoryEpisode, MemoryCategory, MemoryScope } from "@/lib/memory-api";
import { CATEGORY_CONFIG } from "@/lib/memory-config";
import { CategoryPill } from "./CategoryPill";
import { ScopePill } from "./ScopePill";

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffSecs < 10) return "just now";
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function getDotColor(category: MemoryCategory): string {
  switch (category) {
    case "mandate":
      return "bg-red-400";
    case "guardrail":
      return "bg-amber-400";
    case "reference":
      return "bg-blue-400";
    default:
      return "bg-slate-400";
  }
}

interface TimelineItemProps {
  episode: MemoryEpisode;
  isLast: boolean;
}

export function TimelineItem({ episode, isLast }: TimelineItemProps) {
  const [expanded, setExpanded] = useState(false);
  const config = CATEGORY_CONFIG[episode.category as MemoryCategory];
  const contentPreview =
    episode.content.length > 160
      ? episode.content.slice(0, 160) + "..."
      : episode.content;

  return (
    <div className="relative flex gap-4 pb-6 group">
      <div className="flex flex-col items-center">
        <div
          className={cn(
            "w-3 h-3 rounded-full mt-1.5 shrink-0 ring-4 ring-slate-900",
            getDotColor(episode.category as MemoryCategory)
          )}
        />
        {!isLast && (
          <div className="w-px flex-1 bg-slate-700 group-hover:bg-slate-600 transition-colors" />
        )}
      </div>

      <div
        onClick={() => setExpanded((prev) => !prev)}
        className={cn(
          "flex-1 min-w-0 rounded-lg border border-slate-800 bg-slate-800/50 p-3 cursor-pointer transition-colors",
          "hover:bg-slate-800/80 hover:border-slate-700"
        )}
      >
        <div className="flex items-start justify-between gap-3 mb-2">
          <div className="flex items-center gap-2 min-w-0 flex-wrap">
            <span className="text-base leading-none">{config?.icon}</span>
            <CategoryPill category={episode.category} size="sm" />
            <ScopePill scope={episode.scope as MemoryScope} size="sm" />
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-xs text-slate-500">
              {formatRelativeTime(episode.created_at)}
            </span>
            <ChevronDown
              className={cn(
                "h-3.5 w-3.5 text-slate-500 transition-transform",
                expanded && "rotate-180"
              )}
            />
          </div>
        </div>

        <p className="text-sm text-slate-300 leading-relaxed break-words">
          {expanded ? episode.content : contentPreview}
        </p>

        {expanded && episode.entities && episode.entities.length > 0 && (
          <div className="mt-3 pt-3 border-t border-slate-700/50">
            <div className="flex flex-wrap gap-1.5">
              {episode.entities.map((entity, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 text-[10px] rounded-full bg-slate-700/60 text-slate-400 border border-slate-600/40"
                >
                  {entity}
                </span>
              ))}
            </div>
          </div>
        )}

        {expanded && (
          <div className="mt-2 flex items-center gap-3 text-[11px] text-slate-500">
            <span>{episode.source_description || episode.source}</span>
            <span>{new Date(episode.created_at).toLocaleString()}</span>
            {episode.pinned && (
              <span className="text-amber-400">pinned</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
