import { LayoutDashboard } from "lucide-react";
import { cn } from "@/lib/utils";

interface DashboardHeaderProps {
  status: { status: string } | undefined;
  daysRange: number;
  showRangeDropdown: boolean;
  onToggleDropdown: () => void;
  onRangeChange: (days: number) => void;
}

const TIME_RANGE_OPTIONS = [
  { value: 1, label: "1d" },
  { value: 7, label: "7d" },
  { value: 14, label: "14d" },
  { value: 30, label: "30d" },
];

export function DashboardHeader({
  status,
  daysRange,
  onRangeChange,
}: DashboardHeaderProps) {
  return (
    <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
      <div className="px-6 lg:px-8 h-12 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <LayoutDashboard className="h-4.5 w-4.5 text-slate-400" />
          <h1 className="text-base font-semibold text-slate-100">
            Dashboard
          </h1>
          {status && (
            <div className={cn(
              "flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium uppercase tracking-wide",
              status.status === "healthy"
                ? "bg-emerald-500/10 text-emerald-400"
                : "bg-amber-500/10 text-amber-400"
            )}>
              <span className={cn(
                "w-1.5 h-1.5 rounded-full",
                status.status === "healthy" ? "bg-emerald-500" : "bg-amber-500"
              )} />
              {status.status}
            </div>
          )}
        </div>
        <div className="flex items-center rounded-lg border border-slate-700 bg-slate-800 p-0.5">
          {TIME_RANGE_OPTIONS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => onRangeChange(value)}
              className={cn(
                "px-2.5 py-1 text-xs font-medium rounded-md transition-all duration-150",
                daysRange === value
                  ? "bg-amber-600 text-white shadow-sm"
                  : "text-slate-400 hover:text-slate-200"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    </header>
  );
}
