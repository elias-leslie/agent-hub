"use client";

import { cn } from "@/lib/utils";
import type { MemoryScope } from "@/lib/memory-api";
import { SCOPE_CONFIG } from "@/lib/memory-config";

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
