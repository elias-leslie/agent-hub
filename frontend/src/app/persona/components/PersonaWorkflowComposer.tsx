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

export type WorkflowTaskMode = "build" | "bug" | "review" | "research" | "release";

const MODE_LABELS: Array<{ value: WorkflowTaskMode; label: string; detail: string }> = [
  { value: "build", label: "Build", detail: "Feature or solid refactor" },
  { value: "bug", label: "Bug", detail: "Tight fix and regression control" },
  { value: "review", label: "Review", detail: "Audit before changing" },
  { value: "research", label: "Research", detail: "Bounded evidence first" },
  { value: "release", label: "Release", detail: "Final pass and ship gates" },
];

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
    "Do not expand the runtime tool surface. Execution should stay within core read, write, edit, bash capabilities.",
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
      ? "Review the current implementation or evidence. Only make changes if defects are clear and bounded."
      : mode === "research"
        ? "Gather only the evidence needed for the next decision. Avoid broad speculative work."
        : mode === "release"
          ? "Prepare the smallest safe release-ready delta. Keep verification explicit."
          : mode === "bug"
            ? "Fix the defect with the smallest coherent change set and protect against regressions."
            : "Implement the best thin solution without overengineering.";

  return {
    project_id: project?.id ?? "agent-hub",
    parent_session_id: parentSessionId,
    shared_context,
    clarify: {
      task: "Clarify the real operator goal, missing assumptions, and acceptance bar. Keep concise.",
      max_turns: 1,
      use_memory: true,
    },
    plan: {
      task: "Produce a staged plan that keeps reuse high, UI truthful, and verification concrete.",
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
      task: "Review output for behavior regressions, UX confusion, missing evidence, and overengineering.",
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
        return;
      }
      const request = buildWorkflowRequest(task, selectedProject, mode, parentSessionId);
      const singleStageRequest: WorkflowRequest = {
        project_id: request.project_id,
        parent_session_id: request.parent_session_id,
        shared_context: buildSharedContext(task, selectedProject, mode),
        [stageName]: request[stageName],
      };
      const result = await runPersonaWorkflow(singleStageRequest);
      setWorkflow((current) => {
        if (!current) {
          return result;
        }
        const nextStages = current.stages.map((stage) =>
          stage.stage === stageName ? result.stages[0] : stage,
        );
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Workflow failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <section
      data-testid="persona-workflow-composer"
      className="rounded-[28px] border border-slate-800/70 bg-slate-900/80 p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            <Sparkles className="h-3.5 w-3.5 text-amber-300" />
            Staged workflow
          </div>
          <h3 className="mt-2 text-lg font-semibold text-slate-50">
            Clarify. Plan. Execute. Review. QA.
          </h3>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            Run the operator workflow in the open, approve stages, and rerun only the slice that needs correction.
          </p>
        </div>
        <div className="rounded-full border border-slate-700 bg-slate-950/70 px-2.5 py-1 text-xs text-slate-300">
          {workflow?.stages.length ?? 0} stages
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
        placeholder="Describe the real work. Focus on what success looks like and where the operator should be careful."
      />

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void runWorkflow()}
          disabled={running || !task.trim()}
          className="inline-flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-950/20 px-3 py-2 text-sm font-medium text-amber-200 transition hover:border-amber-400/30 hover:bg-amber-950/30 disabled:opacity-60"
        >
          <PlayCircle className="h-4 w-4" />
          {running ? "Running workflow…" : "Run workflow"}
        </button>
        {workflow ? (
          <div className="rounded-full border border-slate-700 bg-slate-950/70 px-2.5 py-1 text-xs text-slate-300">
            {workflow.total_input_tokens + workflow.total_output_tokens} total tokens
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="mt-3 rounded-2xl border border-rose-500/20 bg-rose-950/20 px-3 py-2 text-sm text-rose-200">
          {error}
        </div>
      ) : null}

      <div className="mt-4 space-y-3">
        {workflow?.stages.map((stage) => (
          <div key={stage.stage} className="rounded-[24px] border border-slate-800/70 bg-slate-950/70 p-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  {stage.stage}
                </div>
                <div className="mt-1 text-sm font-medium text-slate-100">
                  {stage.agent_used || stage.provider}
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {stage.provider}/{stage.model} · {stage.usage.total_tokens} tokens
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() =>
                    setApprovedStages((current) => ({
                      ...current,
                      [stage.stage]: !current[stage.stage],
                    }))
                  }
                  className={cn(
                    "inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium transition",
                    approvedStages[stage.stage]
                      ? "border-emerald-500/20 bg-emerald-950/20 text-emerald-200"
                      : "border-slate-700 bg-slate-900/80 text-slate-200 hover:border-slate-600 hover:bg-slate-800",
                  )}
                >
                  <CheckCircle2 className="h-4 w-4" />
                  {approvedStages[stage.stage] ? "Approved" : "Approve"}
                </button>
                <button
                  type="button"
                  onClick={() => void runWorkflow(stage.stage)}
                  disabled={running}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800 disabled:opacity-60"
                >
                  <RotateCcw className="h-4 w-4" />
                  Rerun
                </button>
              </div>
            </div>
            <pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded-2xl border border-slate-800/70 bg-slate-950 px-3 py-3 text-sm leading-6 text-slate-200">
              {stage.content}
            </pre>
          </div>
        ))}
      </div>
    </section>
  );
}
