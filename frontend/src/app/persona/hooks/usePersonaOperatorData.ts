'use client'

import { useDeferredValue, useEffect, useMemo, useState } from 'react'

import { useToastActions } from '@/components/error/toast'
import {
  createPersonaAutomation,
  deletePersonaAutomation,
  fetchPersonaAutomations,
  fetchPersonaOperatorPreview,
  type PersonaAutomation,
  triggerPersonaAutomation,
  updatePersonaAutomation,
} from '@/lib/api/persona-operator'
import {
  type ExecutionPermission,
  fetchExecutionPermission,
  fetchProjectPermissions,
  type ProjectPermission,
} from '@/lib/api/project-permissions'
import type { SessionListItem } from '@/lib/api/sessions'
import type { PreviewProjectOption } from '@/types/agent-preview'
import type { PersonaRuntimeState } from './usePersonaRuntime'

function toProjectOptions(
  permissions: ProjectPermission[],
): PreviewProjectOption[] {
  return permissions
    .filter((permission) => permission.permission_tier !== 'off')
    .map((permission) => ({
      id: permission.project_id,
      name: permission.project_id,
      rootPath: permission.root_path,
    }))
}

export interface UsePersonaOperatorDataResult {
  projectPermissions: ProjectPermission[]
  projectOptions: PreviewProjectOption[]
  selectedProject: PreviewProjectOption | null
  selectedProjectPermission: ProjectPermission | null
  executionPermission: ExecutionPermission | null
  workflowParentSessionId: string | null
  preview: Awaited<ReturnType<typeof fetchPersonaOperatorPreview>> | null
  previewLoading: boolean
  previewError: string | null
  jobs: PersonaAutomation[]
  jobsLoading: boolean
  jobsError: string | null
  savingAutomation: boolean
  triggeringJobId: string | null
  refreshEverything: () => Promise<void>
  saveAutomation: (
    jobId: string | null,
    payload: {
      name: string
      schedule_type: 'at' | 'every' | 'cron'
      schedule_value: string
      payload_message: string
    },
  ) => Promise<void>
  toggleAutomation: (job: PersonaAutomation) => Promise<void>
  removeAutomation: (jobId: string) => Promise<void>
  runAutomationNow: (job: PersonaAutomation) => Promise<void>
}

export function usePersonaOperatorData(
  selectedProjectId: string,
  onProjectChange: (projectId: string) => void,
  focusSession: SessionListItem | null,
  runtime: PersonaRuntimeState,
  onSelectSession: (sessionId: string | null) => void,
  onTabChange: (tab: 'workflow' | 'insights' | 'lanes' | 'automations') => void,
): UsePersonaOperatorDataResult {
  const toast = useToastActions()

  const [projectPermissions, setProjectPermissions] = useState<
    ProjectPermission[]
  >([])
  const [executionPermission, setExecutionPermission] =
    useState<ExecutionPermission | null>(null)
  const [workflowPrompt] = useState('')
  const deferredWorkflowPrompt = useDeferredValue(workflowPrompt)
  const [preview, setPreview] =
    useState<UsePersonaOperatorDataResult['preview']>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [jobs, setJobs] = useState<PersonaAutomation[]>([])
  const [jobsLoading, setJobsLoading] = useState(true)
  const [jobsError, setJobsError] = useState<string | null>(null)
  const [savingAutomation, setSavingAutomation] = useState(false)
  const [triggeringJobId, setTriggeringJobId] = useState<string | null>(null)

  const projectOptions = useMemo(() => {
    const options = toProjectOptions(projectPermissions)
    return options.length > 0
      ? options
      : [{ id: 'agent-hub', name: 'agent-hub', rootPath: null }]
  }, [projectPermissions])

  const selectedProject = useMemo(
    () =>
      projectOptions.find((project) => project.id === selectedProjectId) ??
      null,
    [projectOptions, selectedProjectId],
  )

  const selectedProjectPermission = useMemo(
    () =>
      projectPermissions.find(
        (project) => project.project_id === selectedProjectId,
      ) ?? null,
    [projectPermissions, selectedProjectId],
  )

  const workflowParentSessionId = useMemo(() => {
    if (
      focusSession?.agent_slug === 'persona' &&
      !focusSession.parent_session_id
    ) {
      return focusSession.id
    }
    if (
      runtime.primarySession?.agent_slug === 'persona' &&
      !runtime.primarySession.parent_session_id
    ) {
      return runtime.primarySession.id
    }
    return null
  }, [focusSession, runtime.primarySession])

  const loadProjectPermissions = async () => {
    try {
      const permissions = await fetchProjectPermissions()
      setProjectPermissions(permissions)
      if (
        !permissions.some(
          (permission) => permission.project_id === selectedProjectId,
        )
      ) {
        const fallback =
          permissions.find(
            (permission) => permission.project_id === 'agent-hub',
          ) ?? permissions[0]
        if (fallback) {
          onProjectChange(fallback.project_id)
        }
      }
    } catch (err) {
      toast.error(
        err instanceof Error
          ? err.message
          : 'Failed to load project permissions',
      )
    }
  }

  const loadExecutionPermission = async (projectId: string) => {
    try {
      setExecutionPermission(await fetchExecutionPermission(projectId))
    } catch (err) {
      setExecutionPermission(null)
      toast.error(
        err instanceof Error
          ? err.message
          : 'Failed to load execution permission',
      )
    }
  }

  const loadPreview = async (projectId: string, promptInput: string) => {
    try {
      setPreviewLoading(true)
      setPreviewError(null)
      setPreview(
        await fetchPersonaOperatorPreview({
          projectId,
          promptInput:
            promptInput.trim() ||
            'Summarize operator status, blockers, and next best move.',
          taskType: 'chat',
        }),
      )
    } catch (err) {
      setPreviewError(
        err instanceof Error ? err.message : 'Failed to load preview',
      )
    } finally {
      setPreviewLoading(false)
    }
  }

  const loadAutomations = async () => {
    try {
      setJobsLoading(true)
      setJobsError(null)
      setJobs(await fetchPersonaAutomations())
    } catch (err) {
      setJobsError(
        err instanceof Error ? err.message : 'Failed to load automations',
      )
    } finally {
      setJobsLoading(false)
    }
  }

  useEffect(() => {
    void loadProjectPermissions()
    void loadAutomations()
  }, [])

  useEffect(() => {
    if (!selectedProjectId) {
      return
    }
    void loadExecutionPermission(selectedProjectId)
    void loadPreview(selectedProjectId, deferredWorkflowPrompt)
  }, [deferredWorkflowPrompt, selectedProjectId])

  const refreshEverything = async () => {
    await Promise.allSettled([
      runtime.refresh(),
      loadProjectPermissions(),
      loadExecutionPermission(selectedProjectId),
      loadPreview(selectedProjectId, deferredWorkflowPrompt),
      loadAutomations(),
    ])
  }

  const saveAutomation = async (
    jobId: string | null,
    payload: {
      name: string
      schedule_type: 'at' | 'every' | 'cron'
      schedule_value: string
      payload_message: string
    },
  ) => {
    try {
      setSavingAutomation(true)
      if (jobId) {
        await updatePersonaAutomation(jobId, payload)
      } else {
        await createPersonaAutomation(payload)
      }
      await loadAutomations()
      toast.success(jobId ? 'Automation updated' : 'Automation created')
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : 'Failed to save automation',
      )
    } finally {
      setSavingAutomation(false)
    }
  }

  const toggleAutomation = async (job: PersonaAutomation) => {
    try {
      setSavingAutomation(true)
      await updatePersonaAutomation(job.id, { enabled: !job.enabled })
      await loadAutomations()
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : 'Failed to update automation',
      )
    } finally {
      setSavingAutomation(false)
    }
  }

  const removeAutomation = async (jobId: string) => {
    try {
      setSavingAutomation(true)
      await deletePersonaAutomation(jobId)
      await loadAutomations()
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : 'Failed to delete automation',
      )
    } finally {
      setSavingAutomation(false)
    }
  }

  const runAutomationNow = async (job: PersonaAutomation) => {
    try {
      setTriggeringJobId(job.id)
      const result = await triggerPersonaAutomation(job.id)
      await Promise.allSettled([loadAutomations(), runtime.refresh()])
      if (result.session_id) {
        onSelectSession(result.session_id)
        onTabChange('lanes')
      }
      toast.success(
        result.session_id
          ? 'Automation running in thread'
          : 'Automation triggered',
      )
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : 'Failed to run automation',
      )
    } finally {
      setTriggeringJobId(null)
    }
  }

  return {
    projectPermissions,
    projectOptions,
    selectedProject,
    selectedProjectPermission,
    executionPermission,
    workflowParentSessionId,
    preview,
    previewLoading,
    previewError,
    jobs,
    jobsLoading,
    jobsError,
    savingAutomation,
    triggeringJobId,
    refreshEverything,
    saveAutomation,
    toggleAutomation,
    removeAutomation,
    runAutomationNow,
  }
}
