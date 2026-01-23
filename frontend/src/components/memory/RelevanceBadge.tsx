"use client";

import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { Tooltip } from "./Tooltip";

export function RelevanceBadge({ score }: { score: number }) {
  const percentage = Math.round(score * 100);
  const color =
    percentage >= 80
      ? "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10"
      : percentage >= 60
        ? "text-blue-600 dark:text-blue-400 bg-blue-500/10"
        : "text-slate-600 dark:text-slate-400 bg-slate-500/10";

  return (
    <Tooltip content={`Semantic similarity: ${percentage}%`}>
      <span
        className={cn(
          "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold tabular-nums cursor-help",
          color
        )}
      >
        <Sparkles className="h-2.5 w-2.5" />
        {percentage}%
      </span>
    </Tooltip>
  );
}
