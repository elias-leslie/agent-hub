"use client";

import { useState, useRef, useEffect } from "react";
import { Clock, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

const TIME_RANGES = [
  { value: "6h", label: "6h" },
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
  { value: "all", label: "All" },
] as const;

export type TimeRange = (typeof TIME_RANGES)[number]["value"];

interface TimeRangeDropdownProps {
  value: TimeRange;
  onChange: (value: TimeRange) => void;
}

export function TimeRangeDropdown({ value, onChange }: TimeRangeDropdownProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  const activeLabel = TIME_RANGES.find((r) => r.value === value)?.label ?? value;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={cn(
          "flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors",
          "border border-slate-200 dark:border-slate-700",
          "bg-white dark:bg-slate-800/80 hover:bg-slate-50 dark:hover:bg-slate-700/80",
          "text-slate-600 dark:text-slate-300",
        )}
      >
        <Clock className="w-3 h-3 text-slate-400" />
        <span className="font-mono">{activeLabel}</span>
        <ChevronDown className={cn("w-3 h-3 text-slate-400 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 min-w-[6rem] rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-lg shadow-black/10 py-1">
          {TIME_RANGES.map((range) => (
            <button
              key={range.value}
              onClick={() => {
                onChange(range.value);
                setOpen(false);
              }}
              className={cn(
                "w-full px-3 py-1.5 text-left text-xs font-mono transition-colors",
                range.value === value
                  ? "bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 font-semibold"
                  : "text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700/50",
              )}
            >
              {range.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
