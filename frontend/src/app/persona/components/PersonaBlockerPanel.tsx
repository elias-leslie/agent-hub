"use client";

import Link from "next/link";
import { AlertTriangle, RefreshCw, Settings2, ShieldCheck } from "lucide-react";

import { cn } from "@/lib/utils";
import type { PersonaPulseSummary } from "@/lib/api/persona-stream";
import type { AgentPreview } from "@/types/agent-preview";
import type { ExecutionPermission, ProjectPermission } from "@/lib/api/project-permissions";
import type { PersonaRuntimeState } from "../hooks/usePersonaRuntime";
import { ProvenanceBadge, SectionEyebrow } from "./persona-operator-chrome";

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
  source,
  tone = "neutral",
}: {
  label: string;
  value: string;
  source: "runtime" | "session" | "preview" | "advisory";
  tone?: "neutral" | "warning" | "danger" | "success";
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-2xl border border-slate-800/70 bg-slate-950/70 px-3 py-2.5">
      <div className="space-y-1">
        <span className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</span>
        <div>
          <ProvenanceBadge source={source} />
        </div>
      </div>
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
  const permissionBlocker = executionPermission && !executionPermission.allowed
    ? executionPermission.reason
    : null;
  const hardBlocker = liveActivity?.stall_reason || runtime.error || permissionBlocker || "None surfaced";
  const advisoryWarning = topIssue?.summary || (typeof promptTokens === "number" && promptTokens >= 14000
    ? "Preview budget is heavy; trim prompt sections before relying on long runs."
    : "None surfaced");

  return (
    <section
      data-testid="persona-blocker-panel"
      className="rounded-[28px] border border-slate-800/70 bg-slate-900/80 p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <SectionEyebrow icon={<ShieldCheck className="h-3.5 w-3.5 text-amber-300" />} label="Blockers and capability truth" source="runtime" />
          <h3 className="mt-2 text-lg font-semibold text-slate-50">
            Call out real blockers, not vibes.
          </h3>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
            Hard blockers appear first. Preview budget stays advisory until runtime publishes authoritative prompt totals.
          </p>
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
          label="Hard blocker"
          value={hardBlocker}
          source="runtime"
          tone={hardBlocker === "None surfaced" ? "success" : "danger"}
        />
        <Row
          label="Permission gate"
          value={
            executionPermission
              ? executionPermission.allowed
                ? `${executionPermission.permission_tier} / ${selectedProject?.project_id ?? "unknown"}`
                : executionPermission.reason
              : "Loading"
          }
          source="advisory"
          tone={executionPermission?.allowed ? "success" : executionPermission ? "danger" : "neutral"}
        />
        <Row
          label="Capability gate"
          value="Core only: read, write, edit, bash"
          source="session"
          tone={executionPermission?.allowed === false ? "warning" : "neutral"}
        />
        <Row
          label="Execution"
          value={executionState === "paused" ? "Paused by operator" : "Live"}
          source="session"
          tone={executionState === "paused" ? "warning" : "success"}
        />
        <Row
          label="Auto-run"
          value={heartbeatIntervalMinutes > 0 ? `Every ${heartbeatIntervalMinutes}m` : "Disabled"}
          source="session"
          tone={heartbeatIntervalMinutes > 0 ? "success" : "warning"}
        />
        <Row
          label="Preview budget"
          value={typeof promptTokens === "number" ? `${promptTokens.toLocaleString()} tokens` : "Loading"}
          source="preview"
          tone={promptTone}
        />
        <Row
          label="Advisory warning"
          value={advisoryWarning}
          source="advisory"
          tone={advisoryWarning === "None surfaced" ? "success" : "warning"}
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
