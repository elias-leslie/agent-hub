'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'
import {
  useParams,
  usePathname,
  useRouter,
  useSearchParams,
} from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'
import { fetchAgent, fetchModels, updateAgent } from '@/lib/api'
import { DEFAULT_PREVIEW_SCENARIO } from '@/types/agent-preview'
import { buildAgentUpdatePayload, createAgentFormData } from './agent-form'
import { AgentEditorHeader } from './components/AgentEditorHeader'
import { CommitteeTab } from './components/CommitteeTab'
import { GeneralTab } from './components/GeneralTab'
import { MemoryTab } from './components/MemoryTab'
import { ModelsTab } from './components/ModelsTab'
import { ParametersTab } from './components/ParametersTab'
import { PromptsTab } from './components/PromptsTab'
import { getAgentEditorTabs, Sidebar } from './components/Sidebar'
import { useAgentPreview } from './hooks/useAgentPreview'
import type { Agent, PreviewScenario, PreviewTaskType, TabId } from './types'

function isAgentTab(value: string | null, slug: string): value is TabId {
  return getAgentEditorTabs(slug).some((tab) => tab.id === value)
}

export default function AgentEditorPage() {
  const params = useParams()
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const slug = params.slug as string

  // Redirect persona slug to dedicated settings page
  useEffect(() => {
    if (slug === 'persona') {
      router.replace('/persona/settings')
    }
  }, [slug, router])

  const [formData, setFormData] = useState<Partial<Agent>>({})
  const [hasChanges, setHasChanges] = useState(false)
  const [showInlinePreview, setShowInlinePreview] = useState(false)
  const [previewMode, setPreviewMode] = useState<PreviewTaskType>('chat')
  const [previewScenario, setPreviewScenario] = useState<PreviewScenario>(
    () => ({
      ...DEFAULT_PREVIEW_SCENARIO,
    }),
  )
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const {
    data: agent,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['agent', slug],
    queryFn: () => fetchAgent(slug),
    enabled: !!slug,
  })

  const { data: availableModels = [] } = useQuery({
    queryKey: ['models', 'options'],
    queryFn: fetchModels,
  })

  const {
    data: preview,
    refetch: refetchPreview,
    isFetching: previewFetching,
    error: previewQueryError,
  } = useAgentPreview({
    slug,
    previewMode,
    scenario: previewScenario,
    enabled: showInlinePreview && !!slug,
  })

  const mutation = useMutation({
    mutationFn: (data: Partial<Agent>) => updateAgent(slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agent', slug] })
      queryClient.invalidateQueries({ queryKey: ['agents'] })
      setHasChanges(false)
    },
  })

  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (hasChanges) {
        e.preventDefault()
        e.returnValue =
          'You have unsaved changes. Are you sure you want to leave?'
        return e.returnValue
      }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [hasChanges])

  useEffect(() => {
    if (agent) {
      setFormData(createAgentFormData(agent))
    }
  }, [agent])

  const updateField = useCallback(
    <K extends keyof Agent>(field: K, value: Agent[K]) => {
      setFormData((prev) => ({ ...prev, [field]: value }))
      setHasChanges(true)
    },
    [],
  )
  const setActiveTab = useCallback(
    (tab: TabId) => {
      const nextParams = new URLSearchParams(searchParams.toString())
      if (tab === 'general') {
        nextParams.delete('tab')
      } else {
        nextParams.set('tab', tab)
      }
      const query = nextParams.toString()
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      })
    },
    [pathname, router, searchParams],
  )
  const updatePreviewScenario = useCallback(
    (updates: Partial<PreviewScenario>) => {
      setPreviewScenario((prev) => ({ ...prev, ...updates }))
    },
    [],
  )

  const handleSave = () => {
    mutation.mutate(buildAgentUpdatePayload(formData))
  }

  const handlePreview = () => {
    setActiveTab('prompts')
    setShowInlinePreview(true)
    if (showInlinePreview) {
      void refetchPreview()
    }
  }
  const previewError =
    previewQueryError instanceof Error
      ? previewQueryError.message
      : previewQueryError
        ? 'Failed to load preview'
        : null
  const tabParam = searchParams.get('tab')
  const activeTab: TabId = isAgentTab(tabParam, slug) ? tabParam : 'general'

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    )
  }

  if (error || !agent) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <AlertCircle className="h-10 w-10 text-red-500 mx-auto mb-3" />
          <p className="text-sm text-slate-400">Agent not found</p>
          <button
            onClick={() => router.push('/agents')}
            className="mt-4 px-4 py-2 text-sm font-medium text-amber-500 hover:underline"
          >
            Back to Agents
          </button>
        </div>
      </div>
    )
  }

  const activeTabLabel =
    getAgentEditorTabs(slug).find((tab) => tab.id === activeTab)?.label ??
    'Editor'
  const activeTabDescription =
    getAgentEditorTabs(slug).find((tab) => tab.id === activeTab)?.description ??
    'Adjust this slice of the agent runtime profile.'

  return (
    <div className="page-shell">
      <div className="page-backdrop" />
      <AgentEditorHeader
        agent={agent}
        hasChanges={hasChanges}
        isSaving={mutation.isPending}
        onSave={handleSave}
        onPreview={handlePreview}
        onOpenSidebar={() => setSidebarOpen(true)}
        activeTabLabel={activeTabLabel}
      />

      {mutation.isSuccess && (
        <div className="fixed top-20 right-6 z-50 flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-950/40 border border-emerald-800 text-emerald-400 text-sm shadow-lg">
          <CheckCircle2 className="h-4 w-4" />
          Agent saved successfully
        </div>
      )}
      {mutation.isError && (
        <div className="fixed top-20 right-6 z-50 flex items-center gap-2 px-4 py-2 rounded-lg bg-red-950/40 border border-red-800 text-red-400 text-sm shadow-lg">
          <AlertCircle className="h-4 w-4" />
          Failed to save agent
        </div>
      )}

      <div className="page-container">
        <div className="page-frame">
          <div className="flex flex-col gap-6 xl:flex-row">
            <Sidebar
              activeTab={activeTab}
              agent={agent}
              onTabChange={setActiveTab}
              mobileOpen={sidebarOpen}
              onMobileClose={() => setSidebarOpen(false)}
            />

            <main className="min-w-0 flex-1">
              <section className="panel-surface animate-fade-up">
                <div className="border-b border-slate-800/80 px-5 py-5 lg:px-6">
                  <div className="section-header gap-4">
                    <div>
                      <p className="section-kicker">Runtime Profile</p>
                      <h2 className="section-heading mt-2">{activeTabLabel}</h2>
                      <p className="section-copy mt-2 max-w-3xl">
                        {activeTabDescription}
                      </p>
                    </div>
                    <div className="page-meta">
                      <span className="page-pill">Agent runtime</span>
                      <span className="page-pill">Prompt preview</span>
                    </div>
                  </div>
                </div>
                <div className="px-5 py-5 lg:px-6 lg:py-6">
                  <div className="max-w-5xl">
                    {activeTab === 'general' && (
                      <GeneralTab
                        formData={formData}
                        updateField={updateField}
                      />
                    )}
                    {activeTab === 'models' && (
                      <ModelsTab
                        formData={formData}
                        availableModels={availableModels}
                        updateField={updateField}
                      />
                    )}
                    {activeTab === 'parameters' && (
                      <ParametersTab
                        formData={formData}
                        availableModels={availableModels}
                        updateField={updateField}
                      />
                    )}
                    {activeTab === 'prompts' && (
                      <PromptsTab
                        agentSlug={slug}
                        preview={preview}
                        previewFetching={previewFetching}
                        previewError={previewError}
                        showInlinePreview={showInlinePreview}
                        setShowInlinePreview={setShowInlinePreview}
                        previewMode={previewMode}
                        setPreviewMode={setPreviewMode}
                        previewScenario={previewScenario}
                        onPreviewScenarioChange={updatePreviewScenario}
                        refetchPreview={refetchPreview}
                      />
                    )}
                    {activeTab === 'memory' && (
                      <MemoryTab
                        formData={formData}
                        updateField={updateField}
                      />
                    )}
                    {activeTab === 'committee' && (
                      <CommitteeTab
                        formData={formData}
                        updateField={updateField}
                        availableModels={availableModels}
                      />
                    )}
                  </div>
                </div>
              </section>
            </main>
          </div>
        </div>
      </div>
    </div>
  )
}
