import { Clock, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

interface DashboardHeaderProps {
  status: { status: string } | undefined;
  daysRange: number;
  showRangeDropdown: boolean;
  onToggleDropdown: () => void;
  onRangeChange: (days: number) => void;
}

export function DashboardHeader({
  status,
  daysRange,
  showRangeDropdown,
  onToggleDropdown,
  onRangeChange,
}: DashboardHeaderProps) {
  const timeRangeOptions = [1, 7, 14, 30];

  return (
    <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
      <div className="px-6 lg:px-8 h-12 flex items-center justify-between">
        <div className="flex items-center gap-3">
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
        <div className="relative">
          <button
            onClick={onToggleDropdown}
            className="flex items-center gap-2 px-2 py-1 rounded-md text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 transition-colors font-mono"
          >
            <Clock className="h-3.5 w-3.5" />
            <span>{daysRange}-day view</span>
            <ChevronDown className="h-3 w-3" />
          </button>
          {showRangeDropdown && (
            <div className="absolute right-0 top-full mt-1 py-1 w-28 rounded-lg bg-slate-800 border border-slate-700 shadow-xl z-30">
              {timeRangeOptions.map((days) => (
                <button
                  key={days}
                  onClick={() => onRangeChange(days)}
                  className={cn(
                    "w-full px-3 py-1.5 text-left text-xs font-mono",
                    days === daysRange
                      ? "text-emerald-400 bg-emerald-500/10"
                      : "text-slate-300 hover:bg-slate-700"
                  )}
                >
                  {days === 1 ? "Today" : `${days} days`}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
