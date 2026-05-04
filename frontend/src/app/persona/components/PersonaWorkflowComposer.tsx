'use client'

import { PlayCircle, RotateCcw } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  runPersonaWorkflow,
  type WorkflowRequest,
  type WorkflowResult,
  type WorkflowStageName,
} from '@/lib/api/persona-operator'
import { cn } from '@/lib/utils'
import type { PreviewProjectOption } from '@/types/agent-preview'

export type WorkflowTaskMode =
  | 'build'
  | 'bug'
  | 'review'
  | 'research'
  | 'release'

const MODE_LABELS: Array<{ value: WorkflowTaskMode; label: string }> = [
  { value: 'build', label: 'Build' },
  { value: 'bug', label: 'Bug' },
  { value: 'review', label: 'Review' },
  { value: 'research', label: 'Research' },
  { value: 'release', label: 'Release' },
]
const WORKFLOW_STAGE_ORDER: WorkflowStageName[] = [
  'clarify',
  'plan',
  'execute',
  'review',
  'qa',
]

interface PersonaWorkflowComposerProps {
  projectOptions: PreviewProjectOption[]
  selectedProjectId: string
  parentSessionId: string | null
  onProjectChange: (projectId: string) => void
  onPromptChange: (prompt: string) => void
}

function buildSharedContext(
  task: string,
  project: PreviewProjectOption | null,
  mode: WorkflowTaskMode,
): string {
  return [
    `Operator request:\n${task}`,
    `Project: ${project?.id ?? 'agent-hub'}`,
    project?.rootPath ? `Working directory: ${project.rootPath}` : null,
    `Mode: ${mode}`,
    'Keep solution DRY, SOTA, and non-overengineered.',
    'Do not expand runtime tool surface. Execution stays within read, write, edit, bash.',
  ]
    .filter(Boolean)
    .join('\n\n')
}

function buildWorkflowRequest(
  task: string,
  project: PreviewProjectOption | null,
  mode: WorkflowTaskMode,
  parentSessionId: string | null,
): WorkflowRequest {
  const workingDir = project?.rootPath ?? null
  const shared_context = buildSharedContext(task, project, mode)
  const executeTask =
    mode === 'review'
      ? 'Review current implementation or evidence. Change only if defects are clear and bounded.'
      : mode === 'research'
        ? 'Gather only evidence needed for next decision. Avoid broad speculative work.'
        : mode === 'release'
          ? 'Prepare smallest safe release-ready delta. Keep verification explicit.'
          : mode === 'bug'
            ? 'Fix defect with smallest coherent change set and protect against regressions.'
            : 'Implement best thin solution without overengineering.'

  return {
    project_id: project?.id ?? 'agent-hub',
    parent_session_id: parentSessionId,
    shared_context,
    clarify: {
      task: 'Clarify real operator goal, missing assumptions, and acceptance bar. Keep concise.',
      max_turns: 1,
      use_memory: true,
    },
    plan: {
      task: 'Produce staged plan that keeps reuse high, UI truthful, and verification concrete.',
      max_turns: 1,
      use_memory: true,
    },
    execute: {
      task: executeTask,
      max_turns: mode === 'research' ? 3 : 6,
      use_memory: true,
      execute_tools: mode !== 'review',
      working_dir: workingDir,
      phase: mode === 'review' ? 'review' : 'implementation',
    },
    review: {
      task: 'Review output for regressions, UX confusion, missing evidence, and overengineering.',
      max_turns: 1,
      use_memory: true,
    },
    qa: {
      task: 'State final pass/fail, exact remaining risks, and required verification.',
      max_turns: 1,
      use_memory: true,
    },
  }
}

export function PersonaWorkflowComposer({
  projectOptions,
  selectedProjectId,
  parentSessionId,
  onProjectChange,
  onPromptChange,
}: PersonaWorkflowComposerProps) {
  const [task, setTask] = useState('')
  const [mode, setMode] = useState<WorkflowTaskMode>('build')
  const [workflow, setWorkflow] = useState<WorkflowResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [staleStages, setStaleStages] = useState<
    Partial<Record<WorkflowStageName, WorkflowStageName>>
  >({})
  const selectedProject = useMemo(
    () =>
      projectOptions.find((option) => option.id === selectedProjectId) ?? null,
    [projectOptions, selectedProjectId],
  )

  const runWorkflow = async (stageName?: WorkflowStageName) => {
    if (!task.trim()) {
      return
    }
    setRunning(true)
    setError(null)
    onPromptChange(task)
    try {
      if (!stageName) {
        const result = await runPersonaWorkflow(
          buildWorkflowRequest(task, selectedProject, mode, parentSessionId),
        )
        setWorkflow(result)
        setStaleStages({})
        return
      }
      const request = buildWorkflowRequest(
        task,
        selectedProject,
        mode,
        parentSessionId,
      )
      const selectedStageIndex = WORKFLOW_STAGE_ORDER.indexOf(stageName)
      const staleIndices = WORKFLOW_STAGE_ORDER.slice(0, selectedStageIndex + 1)
        .map((workflowStage, index) =>
          staleStages[workflowStage] ? index : -1,
        )
        .filter((index) => index >= 0)
      const startIndex =
        staleIndices.length > 0 ? Math.min(...staleIndices) : selectedStageIndex
      const rerunStageNames = WORKFLOW_STAGE_ORDER.slice(
        startIndex,
        selectedStageIndex + 1,
      )
      const priorOutputs = (workflow?.stages ?? [])
        .filter(
          (stage) => WORKFLOW_STAGE_ORDER.indexOf(stage.stage) < startIndex,
        )
        .map(
          (stage) => `${stage.stage.toUpperCase()} OUTPUT:\n${stage.content}`,
        )
      const rerunStagePayload = Object.fromEntries(
        rerunStageNames.map((workflowStage) => [
          workflowStage,
          request[workflowStage],
        ]),
      )
      const singleStageRequest = {
        project_id: request.project_id,
        parent_session_id: request.parent_session_id,
        shared_context: [
          buildSharedContext(task, selectedProject, mode),
          priorOutputs.length > 0
            ? `Prior workflow outputs:\n\n${priorOutputs.join('\n\n')}`
            : null,
        ]
          .filter(Boolean)
          .join('\n\n'),
        ...rerunStagePayload,
      } as WorkflowRequest
      const result = await runPersonaWorkflow(singleStageRequest)
      setWorkflow((current) => {
        if (!current) {
          return result
        }
        const returnedStages = new Map(
          result.stages.map((stage) => [stage.stage, stage]),
        )
        const nextStages = current.stages.map(
          (stage) => returnedStages.get(stage.stage) ?? stage,
        )
        return {
          ...current,
          stages: nextStages,
          final_output:
            stageName === 'qa' ? result.final_output : current.final_output,
          total_input_tokens:
            current.total_input_tokens + result.total_input_tokens,
          total_output_tokens:
            current.total_output_tokens + result.total_output_tokens,
        }
      })
      setStaleStages((current) => {
        const next = { ...current }
        for (const workflowStage of WORKFLOW_STAGE_ORDER.slice(
          startIndex,
          selectedStageIndex + 1,
        )) {
          delete next[workflowStage]
        }
        for (const workflowStage of WORKFLOW_STAGE_ORDER.slice(
          selectedStageIndex + 1,
        )) {
          next[workflowStage] = stageName
        }
        return next
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Workflow failed')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div data-testid="persona-workflow-composer" className="space-y-3">
      <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
        <textarea
          value={task}
          onChange={(event) => {
            setTask(event.target.value)
            onPromptChange(event.target.value)
          }}
          rows={4}
          className="min-h-[100px] w-full rounded-lg border border-slate-800/55 bg-slate-950/45 px-3 py-2 text-[13px] text-slate-100 outline-none placeholder:text-slate-500"
          placeholder="Describe work. Name the success bar and risk."
        />
        <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-1">
          <select
            value={selectedProjectId}
            onChange={(event) => onProjectChange(event.target.value)}
            className="rounded-lg border border-slate-800/55 bg-slate-950/45 px-3 py-2 text-[13px] text-slate-100 outline-none"
          >
            {projectOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>
          <select
            value={mode}
            onChange={(event) =>
              setMode(event.target.value as WorkflowTaskMode)
            }
            className="rounded-lg border border-slate-800/55 bg-slate-950/45 px-3 py-2 text-[13px] text-slate-100 outline-none"
          >
            {MODE_LABELS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void runWorkflow()}
            disabled={running || !task.trim()}
            className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-700/70 bg-slate-900/60 px-3 py-1.5 text-[13px] font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-900/80 hover:text-slate-50 disabled:opacity-60"
          >
            <PlayCircle className="h-4 w-4" />
            {running ? 'Running…' : 'Run workflow'}
          </button>
        </div>
      </div>

      {parentSessionId || workflow ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
          {parentSessionId ? <span>Root {parentSessionId}</span> : null}
          {workflow ? (
            <span>
              {workflow.total_input_tokens + workflow.total_output_tokens}{' '}
              tokens
            </span>
          ) : null}
        </div>
      ) : null}
      {error ? <div className="text-sm text-rose-300">{error}</div> : null}

      <div className="space-y-3">
        {workflow?.stages.map((stage) => {
          const staleReason = staleStages[stage.stage]
          return (
            <div
              key={stage.stage}
              className={cn(
                'rounded-lg border px-3 py-3',
                staleReason
                  ? 'border-amber-500/25 bg-amber-950/10'
                  : 'border-slate-800/60 bg-slate-950/55',
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                    {stage.stage}
                    {staleReason ? ` · stale after ${staleReason}` : ''}
                  </div>
                  <div className="mt-1 text-sm text-slate-100">
                    {stage.agent_used || stage.provider}
                    {stage.session_id
                      ? ` · ${stage.session_id}`
                      : ' · advisory'}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void runWorkflow(stage.stage)}
                  disabled={running}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-800/70 bg-slate-950/70 px-2.5 py-1.5 text-[11px] font-medium text-slate-300 transition hover:border-slate-700 hover:bg-slate-900/80 hover:text-slate-100 disabled:opacity-60"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Rerun
                </button>
              </div>
              <div className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-300">
                {stage.content}
              </div>
            </div>
          )
        })}
      </div>

      {workflow?.final_output ? (
        <div className="border-t border-slate-800 pt-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            Final output
          </div>
          <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-200">
            {workflow.final_output}
          </div>
        </div>
      ) : null}
    </div>
  )
}
