import { ArrowUp, ArrowDown, ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SortField, SortDirection } from "../lib/types";

export function SortableHeader({
  label,
  field,
  currentField,
  direction,
  onSort,
  icon,
  align = "left",
}: {
  label: string;
  field: SortField;
  currentField: SortField;
  direction: SortDirection;
  onSort: (field: SortField) => void;
  icon?: React.ReactNode;
  align?: "left" | "right";
}) {
  const isActive = currentField === field;

  return (
    <button
      onClick={() => onSort(field)}
      className={cn(
        "flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider transition-colors",
        "text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300",
        isActive && "text-slate-700 dark:text-slate-200",
        align === "right" && "justify-end ml-auto"
      )}
    >
      {icon}
      {label}
      {isActive ? (
        direction === "asc" ? (
          <ArrowUp className="h-3 w-3" />
        ) : (
          <ArrowDown className="h-3 w-3" />
        )
      ) : (
        <ArrowUpDown className="h-3 w-3 opacity-30" />
      )}
    </button>
  );
}
