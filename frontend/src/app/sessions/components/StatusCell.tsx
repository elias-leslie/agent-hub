import { cn } from "@/lib/utils";
import type { LiveActivity } from "@/lib/api/sessions";

function resolveStatusState(status: string, liveActivity?: LiveActivity | null) {
  if (liveActivity?.reapable) {
    return {
      glyph: "◌",
      label: "Reapable",
      dot: "bg-amber-400",
      tone: "border-amber-500/30 bg-amber-500/10 text-amber-200",
    };
  }

  if (liveActivity?.stalled) {
    return {
      glyph: "◐",
      label: "Stalled",
      dot: "bg-amber-400",
      tone: "border-amber-500/30 bg-amber-500/10 text-amber-200",
    };
  }

  if (status === "active" || liveActivity?.lifecycle_state === "working") {
    return {
      glyph: "●",
      label: "Working",
      dot: "bg-emerald-400",
      tone: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
    };
  }

  if (status === "failed" || status === "error") {
    return {
      glyph: "✕",
      label: "Failed",
      dot: "bg-rose-400",
      tone: "border-rose-500/30 bg-rose-500/10 text-rose-200",
    };
  }

  return {
    glyph: "✓",
    label: "Complete",
    dot: "bg-slate-400",
    tone: "border-slate-700 bg-slate-900/80 text-slate-300",
  };
}

export function StatusCell({
  status,
  liveActivity,
}: {
  status: string;
  liveActivity?: LiveActivity | null;
}) {
  const state = resolveStatusState(status, liveActivity);
  const mismatch =
    liveActivity &&
    (status === "completed" || status === "failed" || status === "error") &&
    liveActivity.lifecycle_state === "working";

  return (
    <div className="min-w-[88px] space-y-1">
      <div
        className={cn(
          "inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-[10px] font-mono uppercase tracking-[0.18em]",
          state.tone,
        )}
      >
        <span className="flex items-center gap-1.5">
          <span className="relative flex h-2 w-2">
            <span
              className={cn(
                "absolute inline-flex h-full w-full rounded-full",
                state.dot,
                (status === "active" || liveActivity?.stalled) && "animate-ping opacity-70",
              )}
            />
            <span className={cn("relative inline-flex h-2 w-2 rounded-full", state.dot)} />
          </span>
          <span>{state.glyph}</span>
        </span>
        <span>{state.label}</span>
      </div>

      {mismatch && (
        <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-amber-300">
          status mismatch
        </div>
      )}
    </div>
  );
}
