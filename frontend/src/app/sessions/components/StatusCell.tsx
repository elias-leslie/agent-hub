import { cn } from "@/lib/utils";

export function StatusCell({ status, isLive }: { status: string; isLive?: boolean }) {
  const config: Record<string, { dot: string; bg: string; label: string }> = {
    active: {
      dot: "bg-blue-500",
      bg: "bg-blue-500/10",
      label: "Active",
    },
    completed: {
      dot: "bg-slate-500",
      bg: "",
      label: "Done",
    },
    error: {
      dot: "bg-red-500",
      bg: "bg-red-500/10",
      label: "Error",
    },
    failed: {
      dot: "bg-red-500",
      bg: "bg-red-500/10",
      label: "Failed",
    },
  };

  const { dot, bg, label } = config[status] || config.completed;
  const showPulse = status === "active" || isLive;

  return (
    <div className={cn("flex items-center gap-2 min-w-[70px]", bg && "px-2 py-1 -mx-2 -my-1 rounded")}>
      <span className="relative flex h-2 w-2">
        <span
          className={cn(
            "absolute inline-flex h-full w-full rounded-full",
            dot,
            showPulse && "animate-ping opacity-75"
          )}
        />
        <span className={cn("relative inline-flex rounded-full h-2 w-2", dot)} />
      </span>
      <span className="text-[11px] text-slate-400 font-medium">
        {label}
      </span>
    </div>
  );
}
