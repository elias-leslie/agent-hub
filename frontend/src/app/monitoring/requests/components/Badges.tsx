import { Server, Terminal, Code2, AlertCircle, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function ToolTypeBadge({ type }: { type: string | null }) {
  const config = {
    api: { icon: Server, color: "text-blue-400", bg: "bg-blue-500/10" },
    cli: { icon: Terminal, color: "text-emerald-400", bg: "bg-emerald-500/10" },
    sdk: { icon: Code2, color: "text-purple-400", bg: "bg-purple-500/10" },
  };

  const typeKey = (type?.toLowerCase() || "api") as keyof typeof config;
  const { icon: Icon, color, bg } = config[typeKey] || config.api;

  return (
    <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium", bg, color)}>
      <Icon className="h-3 w-3" />
      {type?.toUpperCase() || "API"}
    </span>
  );
}

export function StatusBadge({ code }: { code: number }) {
  const config = code >= 500
    ? { icon: AlertCircle, color: "text-red-400", bg: "bg-red-500/10" }
    : code >= 400
    ? { icon: AlertCircle, color: "text-amber-400", bg: "bg-amber-500/10" }
    : { icon: CheckCircle2, color: "text-emerald-400", bg: "bg-emerald-500/10" };

  return (
    <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono", config.bg, config.color)}>
      <config.icon className="h-3 w-3" />
      {code}
    </span>
  );
}
