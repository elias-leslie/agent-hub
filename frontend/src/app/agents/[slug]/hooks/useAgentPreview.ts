'use client'

import { useQuery } from '@tanstack/react-query'
import { useDeferredValue } from 'react'

import { fetchPreview } from '@/lib/api'
import type { AgentPreview, PreviewScenario, PreviewTaskType } from '../types'

interface UseAgentPreviewOptions {
  slug: string
  previewMode: PreviewTaskType
  scenario: PreviewScenario
  enabled: boolean
}

function normalizeOptional(value: string): string | undefined {
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : undefined
}

export function useAgentPreview({
  slug,
  previewMode,
  scenario,
  enabled,
}: UseAgentPreviewOptions) {
  const deferredProjectId = useDeferredValue(scenario.projectId)
  const deferredPhase = useDeferredValue(scenario.phase)
  const deferredPromptInput = useDeferredValue(scenario.promptInput)

  return useQuery<AgentPreview>({
    queryKey: [
      'agent-preview',
      slug,
      previewMode,
      normalizeOptional(deferredProjectId) ?? null,
      normalizeOptional(deferredPhase) ?? null,
      normalizeOptional(deferredPromptInput) ?? null,
    ],
    queryFn: () =>
      fetchPreview(slug, {
        taskType: previewMode,
        projectId: normalizeOptional(deferredProjectId),
        phase: normalizeOptional(deferredPhase),
        promptInput: normalizeOptional(deferredPromptInput),
      }),
    enabled: enabled && slug.length > 0,
  })
}
