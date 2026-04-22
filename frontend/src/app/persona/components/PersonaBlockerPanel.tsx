"use client";

import { RefreshCw } from "lucide-react";

import type { PersonaPulseSummary } from "@/lib/api/persona-stream";
import type { AgentPreview } from "@/types/agent-preview";
import type { ExecutionPermission, ProjectPermission } from "@/lib/api/project-permissions";
import type { PersonaRuntimeState } from "../hooks/usePersonaRuntime";
import { EvidencePanel, SectionEyebrow } from "./persona-operator-chrome";

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

function lineTone(tone: "danger" | "warning" | "default") {
  if (tone === "danger") return "border-rose-400/60 text-rose-200";
  if (tone === "warning") return "border-amber-400/60 text-amber-200";
  return "border-slate-700 text-slate-300";
}

export function PersonaBlockerPanel({
  heartbeatIntervalMinutes,
  selectedProject,
  executionPermission,
  runtime,
  pulse,
  preview,
  previewLoading,
  onRefresh,
}: PersonaBlockerPanelProps) {
  const liveActivity = runtime.primarySession?.live_activity ?? null;
  const topIssue = pulse.issue_groups[0] ?? null;
  const promptTokens = preview?.memory_debug?.total_tokens;
  const permissionBlocker = executionPermission && !executionPermission.allowed
    ? executionPermission.reason
    : null;
  const hardBlocker = liveActivity?.stall_reason || runtime.error || permissionBlocker || null;
  const advisory = topIssue?.summary || (typeof promptTokens === "number" && promptTokens >= 14000 ? "Preview is heavy." : null);

  const rows = [
    {
      label: "Blocker",
      value: hardBlocker || advisory || "Clear",
      tone: hardBlocker ? "danger" : advisory ? "warning" : "default",
    },
    {
      label: "Permission",
      value: executionPermission
        ? executionPermission.allowed
          ? `${executionPermission.permission_tier} · ${selectedProject?.project_id ?? "unknown"}`
          : executionPermission.reason
        : previewLoading
          ? "Loading…"
          : "Unavailable",
      tone: executionPermission?.allowed ? "default" : executionPermission ? "danger" : "default",
    },
    {
      label: "Auto-run",
      value: heartbeatIntervalMinutes > 0 ? `Every ${heartbeatIntervalMinutes}m` : "Off",
      tone: heartbeatIntervalMinutes > 0 ? "default" : "warning",
    },
  ] as const;

  return (
    <EvidencePanel data-testid="persona-blocker-panel" className="p-4">
      <div className="flex items-center justify-between gap-3">
        <SectionEyebrow label="Blockers" source={hardBlocker ? "runtime" : advisory ? "advisory" : "session"} />
        <button
          type="button"
          onClick={onRefresh}
          className="rounded-lg border border-slate-800 bg-slate-950/70 p-2 text-slate-400 transition hover:border-slate-700 hover:text-slate-200"
          title="Refresh blocker state"
        >
          <RefreshCw className={previewLoading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
        </button>
      </div>

      <div className="mt-3 space-y-2">
        {rows.map((row) => (
          <div key={row.label} className={`border-l-2 pl-3 ${lineTone(row.tone)}`}>
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">{row.label}</div>
            <div className="mt-1 text-sm">{row.value}</div>
          </div>
        ))}
      </div>
    </EvidencePanel>
  );
}
