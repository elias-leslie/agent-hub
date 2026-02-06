import { cn } from "@/lib/utils";

// ─────────────────────────────────────────────────────────────────────────────
// KPI CARD - Compact metrics display
// ─────────────────────────────────────────────────────────────────────────────

export function KPICard({
  label,
  value,
  subtext,
  icon: Icon,
  status = "neutral",
  pulse = false,
}: {
  label: string;
  value: string;
  subtext?: string;
  icon: React.ComponentType<{ className?: string }>;
  status?: "success" | "warning" | "error" | "neutral";
  pulse?: boolean;
}) {
  const statusConfig = {
    success: {
      border: "border-l-emerald-500",
      glow: "shadow-emerald-500/5",
      dot: "bg-emerald-500",
    },
    warning: {
      border: "border-l-amber-500",
      glow: "shadow-amber-500/5",
      dot: "bg-amber-500",
    },
    error: {
      border: "border-l-red-500",
      glow: "shadow-red-500/5",
      dot: "bg-red-500",
    },
    neutral: {
      border: "border-l-slate-600",
      glow: "",
      dot: "bg-slate-400",
    },
  };

  const config = statusConfig[status];

  return (
    <div
      className={cn(
        "relative overflow-hidden",
        "bg-slate-900/60 backdrop-blur-sm",
        "border border-slate-800/80",
        "border-l-[3px]",
        config.border,
        "rounded-lg",
        "transition-all duration-200",
        "hover:shadow-lg hover:shadow-black/20",
        config.glow,
        "group"
      )}
    >
      {/* Subtle corner accent */}
      <div className="absolute -top-8 -right-8 w-16 h-16 bg-gradient-to-br from-slate-800 to-transparent rounded-full opacity-50" />

      <div className="relative p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
                {label}
              </span>
              {pulse && (
                <span className={cn("w-1.5 h-1.5 rounded-full animate-pulse", config.dot)} />
              )}
            </div>
            <p className="mt-1.5 text-2xl font-semibold tracking-tight text-slate-50 font-mono tabular-nums">
              {value}
            </p>
            {subtext && (
              <p className="mt-0.5 text-xs text-slate-400 truncate">
                {subtext}
              </p>
            )}
          </div>
          <div className="p-2 rounded-md bg-slate-800/80 group-hover:bg-slate-800 transition-colors">
            <Icon className="h-4 w-4 text-slate-400" />
          </div>
        </div>
      </div>
    </div>
  );
}
