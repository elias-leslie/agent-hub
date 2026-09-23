'use client'

import { useDeferredValue, useEffect, useMemo, useState } from 'react'

import { useToastActions } from '@/components/error/toast'
import { fetchPersonaOperatorPreview } from '@/lib/api/persona-operator'
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
  selectedProjectPermission: ProjectPermission | null
  executionPermission: ExecutionPermission | null
  workflowParentSessionId: string | null
  preview: Awaited<ReturnType<typeof fetchPersonaOperatorPreview>> | null
  previewLoading: boolean
  previewError: string | null
  refreshEverything: () => Promise<void>
}

export function usePersonaOperatorData(
  selectedProjectId: string,
  onProjectChange: (projectId: string) => void,
  focusSession: SessionListItem | null,
  runtime: PersonaRuntimeState,
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

  const projectOptions = useMemo(() => {
    const options = toProjectOptions(projectPermissions)
    return options.length > 0
      ? options
      : [{ id: 'agent-hub', name: 'agent-hub', rootPath: null }]
  }, [projectPermissions])

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

  useEffect(() => {
    void loadProjectPermissions()
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
    ])
  }

  return {
    projectPermissions,
    projectOptions,
    selectedProjectPermission,
    executionPermission,
    workflowParentSessionId,
    preview,
    previewLoading,
    previewError,
    refreshEverything,
  }
}
