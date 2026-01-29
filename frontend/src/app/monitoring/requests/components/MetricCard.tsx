import { TrendingUp } from "lucide-react";
import { cn } from "@/lib/utils";

export function MetricCard({
  label,
  value,
  subtext,
  icon: Icon,
  trend,
  status = "neutral",
}: {
  label: string;
  value: string;
  subtext?: string;
  icon: React.ComponentType<{ className?: string }>;
  trend?: "up" | "down" | "flat";
  status?: "success" | "warning" | "error" | "neutral";
}) {
  const statusColors = {
    success: "border-l-emerald-500 shadow-emerald-500/5",
    warning: "border-l-amber-500 shadow-amber-500/5",
    error: "border-l-red-500 shadow-red-500/5",
    neutral: "border-l-slate-600",
  };

  return (
    <div
      className={cn(
        "relative overflow-hidden",
        "bg-slate-900/60 backdrop-blur-sm",
        "border border-slate-800/80 border-l-[3px]",
        statusColors[status],
        "rounded-lg p-4",
        "transition-all duration-200 hover:shadow-lg hover:shadow-black/20",
        "group"
      )}
    >
      <div className="absolute -top-8 -right-8 w-16 h-16 bg-gradient-to-br from-slate-800 to-transparent rounded-full opacity-50" />

      <div className="relative flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
              {label}
            </span>
            {trend && (
              <TrendingUp
                className={cn(
                  "h-3 w-3",
                  trend === "up" && "text-emerald-500",
                  trend === "down" && "text-red-500 rotate-180",
                  trend === "flat" && "text-slate-500 rotate-90"
                )}
              />
            )}
          </div>
          <p className="mt-1.5 text-2xl font-semibold tracking-tight text-slate-50 font-mono tabular-nums">
            {value}
          </p>
          {subtext && (
            <p className="mt-0.5 text-xs text-slate-400 truncate">{subtext}</p>
          )}
        </div>
        <div className="p-2 rounded-md bg-slate-800/80 group-hover:bg-slate-800 transition-colors">
          <Icon className="h-4 w-4 text-slate-400" />
        </div>
      </div>
    </div>
  );
}
