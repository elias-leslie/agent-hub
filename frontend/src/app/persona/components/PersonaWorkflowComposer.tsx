"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, PlayCircle, RotateCcw, Sparkles } from "lucide-react";

import { cn } from "@/lib/utils";
import type { PreviewProjectOption } from "@/types/agent-preview";
import {
  runPersonaWorkflow,
  type WorkflowRequest,
  type WorkflowResult,
  type WorkflowStageName,
} from "@/lib/api/persona-operator";
import { EvidencePanel, ProvenanceBadge, SectionEyebrow, ScopeChip } from "./persona-operator-chrome";

export type WorkflowTaskMode = "build" | "bug" | "review" | "research" | "release";

const MODE_LABELS: Array<{ value: WorkflowTaskMode; label: string; detail: string }> = [
  { value: "build", label: "Build", detail: "Feature or solid refactor" },
  { value: "bug", label: "Bug", detail: "Tight fix and regression control" },
  { value: "review", label: "Review", detail: "Audit before changing" },
  { value: "research", label: "Research", detail: "Bounded evidence first" },
  { value: "release", label: "Release", detail: "Final pass and ship gates" },
];
const WORKFLOW_STAGE_ORDER: WorkflowStageName[] = ["clarify", "plan", "execute", "review", "qa"];

interface PersonaWorkflowComposerProps {
  projectOptions: PreviewProjectOption[];
  selectedProjectId: string;
  parentSessionId: string | null;
  onProjectChange: (projectId: string) => void;
  onPromptChange: (prompt: string) => void;
}

function buildSharedContext(task: string, project: PreviewProjectOption | null, mode: WorkflowTaskMode): string {
  return [
    `Operator request:\n${task}`,
    `Project: ${project?.id ?? "agent-hub"}`,
    project?.rootPath ? `Working directory: ${project.rootPath}` : null,
    `Mode: ${mode}`,
    "Keep solution DRY, SOTA, and non-overengineered.",
    "Do not expand runtime tool surface. Execution stays within read, write, edit, bash.",
  ]
    .filter(Boolean)
    .join("\n\n");
}

function buildWorkflowRequest(
  task: string,
  project: PreviewProjectOption | null,
  mode: WorkflowTaskMode,
  parentSessionId: string | null,
): WorkflowRequest {
  const workingDir = project?.rootPath ?? null;
  const shared_context = buildSharedContext(task, project, mode);
  const executeTask =
    mode === "review"
      ? "Review current implementation or evidence. Change only if defects are clear and bounded."
      : mode === "research"
        ? "Gather only evidence needed for next decision. Avoid broad speculative work."
        : mode === "release"
          ? "Prepare smallest safe release-ready delta. Keep verification explicit."
          : mode === "bug"
            ? "Fix defect with smallest coherent change set and protect against regressions."
            : "Implement best thin solution without overengineering.";

  return {
    project_id: project?.id ?? "agent-hub",
    parent_session_id: parentSessionId,
    shared_context,
    clarify: {
      task: "Clarify real operator goal, missing assumptions, and acceptance bar. Keep concise.",
      max_turns: 1,
      use_memory: true,
    },
    plan: {
      task: "Produce staged plan that keeps reuse high, UI truthful, and verification concrete.",
      max_turns: 1,
      use_memory: true,
    },
    execute: {
      task: executeTask,
      max_turns: mode === "research" ? 3 : 6,
      use_memory: true,
      execute_tools: mode !== "review",
      working_dir: workingDir,
      phase: mode === "review" ? "review" : "implementation",
    },
    review: {
      task: "Review output for regressions, UX confusion, missing evidence, and overengineering.",
      max_turns: 1,
      use_memory: true,
    },
    qa: {
      task: "State final pass/fail, exact remaining risks, and required verification.",
      max_turns: 1,
      use_memory: true,
    },
  };
}

export function PersonaWorkflowComposer({
  projectOptions,
  selectedProjectId,
  parentSessionId,
  onProjectChange,
  onPromptChange,
}: PersonaWorkflowComposerProps) {
  const [task, setTask] = useState("");
  const [mode, setMode] = useState<WorkflowTaskMode>("build");
  const [workflow, setWorkflow] = useState<WorkflowResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [approvedStages, setApprovedStages] = useState<Record<string, boolean>>({});
  const [staleStages, setStaleStages] = useState<Partial<Record<WorkflowStageName, WorkflowStageName>>>({});
  const selectedProject = useMemo(
    () => projectOptions.find((option) => option.id === selectedProjectId) ?? null,
    [projectOptions, selectedProjectId],
  );

  const runWorkflow = async (stageName?: WorkflowStageName) => {
    if (!task.trim()) {
      return;
    }
    setRunning(true);
    setError(null);
    onPromptChange(task);
    try {
      if (!stageName) {
        const result = await runPersonaWorkflow(buildWorkflowRequest(task, selectedProject, mode, parentSessionId));
        setWorkflow(result);
        setApprovedStages({});
        setStaleStages({});
        return;
      }
      const request = buildWorkflowRequest(task, selectedProject, mode, parentSessionId);
      const selectedStageIndex = WORKFLOW_STAGE_ORDER.indexOf(stageName);
      const staleIndices = WORKFLOW_STAGE_ORDER
        .slice(0, selectedStageIndex + 1)
        .map((workflowStage, index) => (staleStages[workflowStage] ? index : -1))
        .filter((index) => index >= 0);
      const startIndex = staleIndices.length > 0 ? Math.min(...staleIndices) : selectedStageIndex;
      const rerunStageNames = WORKFLOW_STAGE_ORDER.slice(startIndex, selectedStageIndex + 1);
      const priorOutputs = (workflow?.stages ?? [])
        .filter((stage) => WORKFLOW_STAGE_ORDER.indexOf(stage.stage) < startIndex)
        .map((stage) => `${stage.stage.toUpperCase()} OUTPUT:\n${stage.content}`);
      const rerunStagePayload = Object.fromEntries(
        rerunStageNames.map((workflowStage) => [workflowStage, request[workflowStage]]),
      );
      const singleStageRequest = {
        project_id: request.project_id,
        parent_session_id: request.parent_session_id,
        shared_context: [
          buildSharedContext(task, selectedProject, mode),
          priorOutputs.length > 0 ? `Prior workflow outputs:\n\n${priorOutputs.join("\n\n")}` : null,
        ]
          .filter(Boolean)
          .join("\n\n"),
        ...rerunStagePayload,
      } as WorkflowRequest;
      const result = await runPersonaWorkflow(singleStageRequest);
      setWorkflow((current) => {
        if (!current) {
          return result;
        }
        const returnedStages = new Map(result.stages.map((stage) => [stage.stage, stage]));
        const nextStages = current.stages.map((stage) => returnedStages.get(stage.stage) ?? stage);
        return {
          ...current,
          stages: nextStages,
          final_output:
            stageName === "qa"
              ? result.final_output
              : current.final_output,
          total_input_tokens: current.total_input_tokens + result.total_input_tokens,
          total_output_tokens: current.total_output_tokens + result.total_output_tokens,
        };
      });
      setApprovedStages((current) => {
        const next = { ...current };
        for (const workflowStage of WORKFLOW_STAGE_ORDER.slice(startIndex)) {
          delete next[workflowStage];
        }
        return next;
      });
      setStaleStages((current) => {
        const next = { ...current };
        for (const workflowStage of WORKFLOW_STAGE_ORDER.slice(startIndex, selectedStageIndex + 1)) {
          delete next[workflowStage];
        }
        for (const workflowStage of WORKFLOW_STAGE_ORDER.slice(selectedStageIndex + 1)) {
          next[workflowStage] = stageName;
        }
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Workflow failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <EvidencePanel data-testid="persona-workflow-composer" className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <SectionEyebrow icon={<Sparkles className="h-3.5 w-3.5 text-amber-300" />} label="Staged workflow" source="advisory" />
          <h3 className="mt-2 text-lg font-semibold text-slate-50">
            Advisory workflow over real stage sessions.
          </h3>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            Clarify, plan, execute, review, and QA stay inspectable. Stage cards show session linkage when backend returns a persisted stage session id.
          </p>
        </div>
        <div className="flex flex-col items-end gap-2 text-right">
          <ScopeChip>{workflow?.stages.length ?? 0} stages</ScopeChip>
          {parentSessionId ? <ScopeChip>Root session · {parentSessionId}</ScopeChip> : null}
        </div>
      </div>

      <div className="mt-4 grid gap-2 md:grid-cols-2">
        <select
          value={selectedProjectId}
          onChange={(event) => onProjectChange(event.target.value)}
          className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none"
        >
          {projectOptions.map((option) => (
            <option key={option.id} value={option.id}>
              {option.name}
            </option>
          ))}
        </select>
        <div className="flex flex-wrap gap-2">
          {MODE_LABELS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setMode(option.value)}
              className={cn(
                "rounded-full border px-3 py-1.5 text-xs font-medium transition",
                mode === option.value
                  ? "border-amber-500/30 bg-amber-950/30 text-amber-200"
                  : "border-slate-700 bg-slate-950 text-slate-300 hover:border-slate-600",
              )}
              title={option.detail}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <textarea
        value={task}
        onChange={(event) => {
          setTask(event.target.value);
          onPromptChange(event.target.value);
        }}
        rows={5}
        className="mt-3 min-h-[128px] w-full rounded-[24px] border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none"
        placeholder="Describe real work. Name success bar and where operator should be careful."
      />

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void runWorkflow()}
          disabled={running || !task.trim()}
          className="inline-flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-950/20 px-3 py-2 text-sm font-medium text-amber-200 transition hover:border-amber-400/30 hover:bg-amber-950/30 disabled:opacity-60"
        >
          <PlayCircle className="h-4 w-4" />
          {running ? "Running advisory workflow…" : "Run advisory workflow"}
        </button>
        {workflow ? (
          <div className="rounded-full border border-slate-700 bg-slate-950/70 px-2.5 py-1 text-xs text-slate-300">
            Workflow tokens · {workflow.total_input_tokens + workflow.total_output_tokens}
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="mt-3 rounded-2xl border border-rose-500/20 bg-rose-950/20 px-3 py-2 text-sm text-rose-200">
          {error}
        </div>
      ) : null}

      <div className="mt-4 space-y-3">
        {workflow?.stages.map((stage) => {
          const staleReason = staleStages[stage.stage];
          const isStale = Boolean(staleReason);
          return (
            <div
              key={stage.stage}
              className={cn(
                "rounded-[24px] border bg-slate-950/70 p-3",
                isStale ? "border-amber-500/30" : "border-slate-800/70",
              )}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                    <span>{stage.stage}</span>
                    <ProvenanceBadge source={stage.session_id ? "session" : "advisory"} />
                    {isStale ? (
                      <span className="rounded-full border border-amber-500/20 bg-amber-950/20 px-2 py-0.5 text-[10px] text-amber-200">
                        Stale after {staleReason} rerun
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-1 text-sm font-medium text-slate-100">
                    {stage.agent_used || stage.provider}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span>{stage.provider}/{stage.model} · {stage.usage.total_tokens} tokens</span>
                    {stage.session_id ? <ScopeChip>Stage session · {stage.session_id}</ScopeChip> : <ScopeChip>Advisory output only</ScopeChip>}
                  </div>
                  {isStale ? (
                    <p className="mt-2 text-xs text-amber-200">
                      Later stage kept for inspection only. Rerun from {staleReason} changed upstream truth.
                    </p>
                  ) : null}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setApprovedStages((current) => ({ ...current, [stage.stage]: !current[stage.stage] }))}
                    className={cn(
                      "inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium transition",
                      approvedStages[stage.stage]
                        ? "border-emerald-500/20 bg-emerald-950/20 text-emerald-200"
                        : "border-slate-700 bg-slate-900/80 text-slate-200 hover:border-slate-600 hover:bg-slate-800",
                    )}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    {approvedStages[stage.stage] ? "Approved" : "Mark approved"}
                  </button>
                  <button
                    type="button"
                    onClick={() => void runWorkflow(stage.stage)}
                    disabled={running}
                    className="inline-flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-950/20 px-3 py-2 text-sm font-medium text-amber-200 transition hover:border-amber-400/30 hover:bg-amber-950/30 disabled:opacity-60"
                  >
                    <RotateCcw className="h-4 w-4" />
                    Rerun through {stage.stage}
                  </button>
                </div>
              </div>
              <div className="mt-3 rounded-2xl border border-slate-800/70 bg-slate-900/60 px-3 py-3 text-sm leading-6 text-slate-300 whitespace-pre-wrap">
                {stage.content}
              </div>
            </div>
          );
        })}
      </div>

      {workflow?.final_output ? (
        <div className="mt-4 rounded-[24px] border border-emerald-500/20 bg-emerald-950/15 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <SectionEyebrow label="Final output" source="advisory" />
          </div>
          <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-emerald-100">{workflow.final_output}</div>
        </div>
      ) : null}
    </EvidencePanel>
  );
}
