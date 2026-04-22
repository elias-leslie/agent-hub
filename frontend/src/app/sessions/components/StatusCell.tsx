import { cn } from "@/lib/utils";
import type { LiveActivity } from "@/lib/api/sessions";

function resolveStatusState(status: string, liveActivity?: LiveActivity | null) {
  if (liveActivity?.reapable) {
    return {
      label: "Reapable",
      dot: "bg-amber-400",
      tone: "text-amber-200",
    };
  }

  if (liveActivity?.stalled) {
    return {
      label: "Stalled",
      dot: "bg-amber-400",
      tone: "text-amber-200",
    };
  }

  if (status === "active" || liveActivity?.lifecycle_state === "working") {
    return {
      label: "Working",
      dot: "bg-emerald-400",
      tone: "text-emerald-200",
    };
  }

  if (status === "failed" || status === "error") {
    return {
      label: "Failed",
      dot: "bg-rose-400",
      tone: "text-rose-200",
    };
  }

  return {
    label: "Ended",
    dot: "bg-slate-500",
    tone: "text-slate-300",
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
    liveActivity
    && (status === "completed" || status === "failed" || status === "error")
    && liveActivity.lifecycle_state === "working";

  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 text-xs font-medium",
        state.tone,
        mismatch && "text-amber-200",
      )}
      title={mismatch ? "Session row and live runtime disagree" : undefined}
    >
      <span className={cn("h-2 w-2 rounded-full", mismatch ? "bg-amber-400" : state.dot)} />
      <span>{mismatch ? `${state.label}*` : state.label}</span>
    </div>
  );
}
