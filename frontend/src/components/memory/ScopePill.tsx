"use client";

import { cn } from "@/lib/utils";
import type { MemoryScope } from "@/lib/memory-api";

export const SCOPE_CONFIG: Record<MemoryScope, { label: string; color: string; bg: string }> = {
  global: {
    label: "Global",
    color: "text-indigo-600 dark:text-indigo-400",
    bg: "bg-indigo-500/10 border-indigo-400/40",
  },
  project: {
    label: "Project",
    color: "text-teal-600 dark:text-teal-400",
    bg: "bg-teal-500/10 border-teal-400/40",
  },
  task: {
    label: "Task",
    color: "text-orange-600 dark:text-orange-400",
    bg: "bg-orange-500/10 border-orange-400/40",
  },
};

export function ScopePill({
  scope,
  onClick,
  isActive,
  size = "sm",
}: {
  scope: MemoryScope;
  onClick?: () => void;
  isActive?: boolean;
  size?: "sm" | "md";
}) {
  const config = SCOPE_CONFIG[scope];

  return (
    <span
      onClick={(e) => {
        if (onClick) {
          e.stopPropagation();
          onClick();
        }
      }}
      className={cn(
        "inline-flex items-center rounded border font-semibold uppercase tracking-wide transition-all",
        size === "sm" ? "px-1.5 py-0.5 text-[9px]" : "px-2 py-1 text-[10px]",
        onClick && "cursor-pointer hover:scale-105 active:scale-95",
        isActive && "ring-2 ring-offset-1 ring-offset-white dark:ring-offset-slate-900",
        config.color,
        config.bg,
        isActive && "ring-current"
      )}
      title={onClick ? "Click to filter by scope" : undefined}
    >
      {config.label}
    </span>
  );
}
