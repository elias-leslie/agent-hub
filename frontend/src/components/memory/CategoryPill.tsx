"use client";

import { cn } from "@/lib/utils";
import type { MemoryCategory } from "@/lib/memory-api";

export const CATEGORY_CONFIG: Record<
  MemoryCategory,
  { icon: string; label: string; color: string; bg: string }
> = {
  coding_standard: {
    icon: "📏",
    label: "Standard",
    color: "text-blue-600 dark:text-blue-400",
    bg: "bg-blue-500/10 border-blue-400/40",
  },
  troubleshooting_guide: {
    icon: "⚠️",
    label: "Gotcha",
    color: "text-amber-600 dark:text-amber-400",
    bg: "bg-amber-500/10 border-amber-400/40",
  },
  system_design: {
    icon: "🏗️",
    label: "Design",
    color: "text-purple-600 dark:text-purple-400",
    bg: "bg-purple-500/10 border-purple-400/40",
  },
  operational_context: {
    icon: "⚙️",
    label: "Ops",
    color: "text-slate-600 dark:text-slate-400",
    bg: "bg-slate-500/10 border-slate-400/40",
  },
  domain_knowledge: {
    icon: "📚",
    label: "Domain",
    color: "text-emerald-600 dark:text-emerald-400",
    bg: "bg-emerald-500/10 border-emerald-400/40",
  },
  active_state: {
    icon: "▶️",
    label: "Active",
    color: "text-cyan-600 dark:text-cyan-400",
    bg: "bg-cyan-500/10 border-cyan-400/40",
  },
};

export function CategoryPill({
  category,
  onClick,
  isActive,
  size = "sm",
}: {
  category: MemoryCategory;
  onClick?: () => void;
  isActive?: boolean;
  size?: "sm" | "md";
}) {
  const config = CATEGORY_CONFIG[category];

  return (
    <span
      onClick={(e) => {
        if (onClick) {
          e.stopPropagation();
          onClick();
        }
      }}
      className={cn(
        "inline-flex items-center gap-1 rounded border font-semibold tracking-wide transition-all",
        size === "sm" ? "px-1.5 py-0.5 text-[9px]" : "px-2 py-1 text-[10px]",
        onClick && "cursor-pointer hover:scale-105 active:scale-95",
        isActive && "ring-2 ring-offset-1 ring-offset-white dark:ring-offset-slate-900",
        config.color,
        config.bg,
        isActive && "ring-current"
      )}
      title={onClick ? "Click to filter by category" : undefined}
    >
      <span>{config.icon}</span>
      <span className="uppercase">{config.label}</span>
    </span>
  );
}
