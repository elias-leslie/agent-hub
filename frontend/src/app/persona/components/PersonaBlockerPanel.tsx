"use client";

import Link from "next/link";
import { AlertTriangle, RefreshCw, Settings2, ShieldCheck } from "lucide-react";

import { cn } from "@/lib/utils";
import type { PersonaPulseSummary } from "@/lib/api/persona-stream";
import type { AgentPreview } from "@/types/agent-preview";
import type { ExecutionPermission, ProjectPermission } from "@/lib/api/project-permissions";
import type { PersonaRuntimeState } from "../hooks/usePersonaRuntime";

interface PersonaBlockerPanelProps {
  executionState: "active" | "paused";
  heartbeatIntervalMinutes: number;
  selectedProject: ProjectPermission | null;
  executionPermission: ExecutionPermission | null;
  runtime: PersonaRuntimeState;
  pulse: PersonaPulseSummary;
  preview: AgentPreview | null;
  previewLoading: boolean;
  onAskStatus: () => void;
  onRefresh: () => void;
}

function Row({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "warning" | "danger" | "success";
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-2xl border border-slate-800/70 bg-slate-950/70 px-3 py-2.5">
      <span className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</span>
      <span
        className={cn(
          "text-right text-sm",
          tone === "success"
            ? "text-emerald-300"
            : tone === "warning"
              ? "text-amber-300"
              : tone === "danger"
                ? "text-rose-300"
                : "text-slate-200",
        )}
      >
        {value}
      </span>
    </div>
  );
}

export function PersonaBlockerPanel({
  executionState,
  heartbeatIntervalMinutes,
  selectedProject,
  executionPermission,
  runtime,
  pulse,
  preview,
  previewLoading,
  onAskStatus,
  onRefresh,
}: PersonaBlockerPanelProps) {
  const liveActivity = runtime.primarySession?.live_activity ?? null;
  const topIssue = pulse.issue_groups[0] ?? null;
  const promptTokens = preview?.memory_debug?.total_tokens;
  const promptTone =
    typeof promptTokens === "number" && promptTokens >= 14000
      ? "warning"
      : "neutral";

  return (
    <section
      data-testid="persona-blocker-panel"
      className="rounded-[28px] border border-slate-800/70 bg-slate-900/80 p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            <ShieldCheck className="h-3.5 w-3.5 text-amber-300" />
            Blockers and capability truth
          </div>
          <h3 className="mt-2 text-lg font-semibold text-slate-50">
            Call out real blockers, not vibes.
          </h3>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-xl border border-slate-700 bg-slate-950/70 p-2 text-slate-300 transition hover:border-slate-600 hover:bg-slate-800"
          title="Refresh blocker state"
        >
          <RefreshCw className={cn("h-4 w-4", previewLoading && "animate-spin")} />
        </button>
      </div>

      <div className="mt-4 space-y-2">
        <Row
          label="Execution"
          value={executionState === "paused" ? "Paused by operator" : "Live"}
          tone={executionState === "paused" ? "warning" : "success"}
        />
        <Row
          label="Auto-run"
          value={heartbeatIntervalMinutes > 0 ? `Every ${heartbeatIntervalMinutes}m` : "Disabled"}
          tone={heartbeatIntervalMinutes > 0 ? "success" : "warning"}
        />
        <Row
          label="Project gate"
          value={
            executionPermission
              ? executionPermission.allowed
                ? `${executionPermission.permission_tier} / ${selectedProject?.project_id ?? "unknown"}`
                : executionPermission.reason
              : "Loading"
          }
          tone={executionPermission?.allowed ? "success" : executionPermission ? "danger" : "neutral"}
        />
        <Row
          label="Tool surface"
          value="Core only: read, write, edit, bash"
        />
        <Row
          label="Prompt budget"
          value={typeof promptTokens === "number" ? `${promptTokens.toLocaleString()} tokens` : "Loading"}
          tone={promptTone}
        />
        <Row
          label="Recent friction"
          value={liveActivity?.stall_reason || runtime.error || topIssue?.summary || "None surfaced"}
          tone={liveActivity?.stall_reason || runtime.error || topIssue ? "warning" : "success"}
        />
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onAskStatus}
          className="inline-flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-950/20 px-3 py-2 text-sm font-medium text-amber-200 transition hover:border-amber-400/30 hover:bg-amber-950/30"
        >
          <AlertTriangle className="h-4 w-4" />
          Ask status now
        </button>
        <Link
          href="/persona/settings"
          className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
        >
          <Settings2 className="h-4 w-4" />
          Settings
        </Link>
      </div>
    </section>
  );
}
