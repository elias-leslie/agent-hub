import { Download, Quote, ThumbsUp, ThumbsDown, CheckCircle2, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import type { MemoryAnalytics } from "@/lib/memory-api";

interface UsageStatsProps {
  data: MemoryAnalytics;
}

export function UsageStats({ data }: UsageStatsProps) {
  const items = [
    { label: "Loaded", value: data.total_loaded, icon: Download, color: "text-sky-400", bg: "bg-sky-500/10" },
    { label: "Cited", value: data.total_cited, icon: Quote, color: "text-emerald-400", bg: "bg-emerald-500/10" },
    { label: "Success", value: data.total_success, icon: CheckCircle2, color: "text-green-400", bg: "bg-green-500/10" },
    { label: "Helpful", value: data.total_helpful, icon: ThumbsUp, color: "text-teal-400", bg: "bg-teal-500/10" },
    { label: "Harmful", value: data.total_harmful, icon: ThumbsDown, color: "text-amber-400", bg: "bg-amber-500/10" },
    { label: "Injections", value: data.total_loaded + data.total_cited, icon: Zap, color: "text-violet-400", bg: "bg-violet-500/10" },
  ];

  return (
    <div className="grid grid-cols-2 gap-3">
      {items.map((item) => (
        <div
          key={item.label}
          className="flex items-center gap-3 p-4 rounded-lg bg-slate-900/60 border border-slate-800/80 hover:shadow-lg hover:shadow-black/20 transition-all duration-200"
        >
          <div className={cn("p-2 rounded-md", item.bg)}>
            <item.icon className={cn("h-4 w-4", item.color)} />
          </div>
          <div>
            <p className="text-xl font-semibold text-slate-50 font-mono tabular-nums">
              {item.value.toLocaleString()}
            </p>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">{item.label}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
