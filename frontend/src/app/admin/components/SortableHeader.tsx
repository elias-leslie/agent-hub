import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import { cn } from "@/lib/utils";

export type SortField = "timestamp" | "client_name" | "endpoint" | "block_reason";
export type SortDirection = "asc" | "desc";

export function SortableHeader({
  label,
  field,
  currentField,
  direction,
  onSort,
  align = "left",
}: {
  label: string;
  field: SortField;
  currentField: SortField;
  direction: SortDirection;
  onSort: (field: SortField) => void;
  align?: "left" | "right";
}) {
  const isActive = currentField === field;
  return (
    <button
      onClick={() => onSort(field)}
      className={cn(
        "flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest transition-colors",
        isActive ? "text-amber-400" : "text-slate-500 hover:text-slate-300",
        align === "right" && "justify-end"
      )}
    >
      {label}
      {isActive ? (
        direction === "asc" ? (
          <ArrowUp className="w-3 h-3" />
        ) : (
          <ArrowDown className="w-3 h-3" />
        )
      ) : (
        <ArrowUpDown className="w-3 h-3 opacity-40" />
      )}
    </button>
  );
}
