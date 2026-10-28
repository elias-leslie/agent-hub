'use client'

import { Loader2 } from 'lucide-react'
import { Suspense, useEffect, useMemo, useRef, useState } from 'react'

import { ChatPanel } from '@/components/chat'
import { useModelsWithSync } from '@/hooks/use-models-catalog'
import { agentHubClient } from '@/lib/agent-hub-client'
import { searchTasks, type TaskSearchItem } from '@/lib/api/tasks'
import { cn } from '@/lib/utils'
import type { Agent } from '@/types/agent'
import { ChatHeader } from './components/ChatHeader'
import type { ChatSessionRow } from './components/ChatSessions'
import { ChatSidebar } from './components/ChatSidebar'
import { useAgentSelection } from './hooks/useAgentSelection'
import { useChatSession } from './hooks/useChatSession'
import {
  fetchProjectConfigs,
  type ProjectConfig,
} from './hooks/useProjectContext'

const FALLBACK_PROJECT: ProjectConfig = {
  id: 'agent-hub',
  name: 'Agent Hub',
  rootPath: '/path/to/agent-hub',
}

function ChatContent() {
  const [showSidebar, setShowSidebar] = useState(true)
  const [projects, setProjects] = useState<ProjectConfig[]>([FALLBACK_PROJECT])
  const [projectsError, setProjectsError] = useState<string | null>(null)
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    null,
  )
  const [projectSearch, setProjectSearch] = useState('')
  const [taskQuery, setTaskQuery] = useState('')
  const [taskResults, setTaskResults] = useState<TaskSearchItem[]>([])
  const [selectedTask, setSelectedTask] = useState<TaskSearchItem | null>(null)
  const [tasksLoading, setTasksLoading] = useState(false)
  const [tasksError, setTasksError] = useState<string | null>(null)
  const [thinkingLevel, setThinkingLevel] = useState('')
  const [selectedModel, setSelectedModel] = useState('')
  const catalog = useModelsWithSync()

  const {
    agents,
    selectedAgent,
    setSelectedAgent,
    loading: agentsLoading,
    error: agentsError,
  } = useAgentSelection()

  useEffect(() => {
    let cancelled = false
    fetchProjectConfigs()
      .then((fetchedProjects) => {
        if (cancelled) return
        const nextProjects =
          fetchedProjects.length > 0 ? fetchedProjects : [FALLBACK_PROJECT]
        setProjects(nextProjects)
        if (
          selectedProjectId &&
          !nextProjects.some((project) => project.id === selectedProjectId)
        ) {
          setSelectedProjectId(null)
          setSelectedTask(null)
        }
        setProjectsError(null)
      })
      .catch((err) => {
        if (cancelled) return
        setProjectsError(
          err instanceof Error ? err.message : 'Failed to load projects',
        )
      })
    return () => {
      cancelled = true
    }
  }, [selectedProjectId])

  useEffect(() => {
    if (selectedAgent?.thinking_level) {
      setThinkingLevel(selectedAgent.thinking_level)
    }
  }, [selectedAgent?.thinking_level])

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  )
  const effectiveProjectId = selectedProject?.id ?? 'agent-hub'
  const contextProjectKey = selectedProject?.id ?? 'general'
  const chatContextKey = `chat:${contextProjectKey}:${selectedAgent?.slug ?? 'loading'}:${selectedTask?.id ?? 'none'}`
  const {
    activeSessionId,
    sessionError,
    setSessionError,
    handleSessionCreated,
    handleSelectSession,
    handleContextChange,
    handleNewSession,
  } = useChatSession({ contextKey: chatContextKey })
  const filteredProjects = useMemo(() => {
    const query = projectSearch.trim().toLowerCase()
    if (!query) return projects
    return projects.filter((project) => {
      const haystack =
        `${project.id} ${project.name} ${project.rootPath ?? ''}`.toLowerCase()
      return haystack.includes(query)
    })
  }, [projectSearch, projects])

  useEffect(() => {
    if (!selectedProject) {
      setTaskResults([])
      setTasksError(null)
      setTasksLoading(false)
      return
    }

    let cancelled = false
    const timer = window.setTimeout(() => {
      setTasksLoading(true)
      searchTasks({
        projectId: selectedProject.id,
        query: taskQuery,
        status: 'pending',
        limit: 25,
      })
        .then((response) => {
          if (cancelled) return
          setTaskResults(response.tasks)
          setTasksError(null)
        })
        .catch((err) => {
          if (cancelled) return
          setTasksError(
            err instanceof Error ? err.message : 'Failed to search tasks',
          )
        })
        .finally(() => {
          if (!cancelled) setTasksLoading(false)
        })
    }, 220)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [selectedProject, taskQuery])

  // A session opened by link or reload is continued by the agent it was started with.
  const agentCheckedFor = useRef<string | null>(null)
  useEffect(() => {
    if (!activeSessionId || agents.length === 0) return
    if (agentCheckedFor.current === activeSessionId) return
    agentCheckedFor.current = activeSessionId
    agentHubClient.sessions
      .get(activeSessionId, { includeMessages: false })
      .then((session) => {
        const agent = agents.find((a) => a.slug === session.agent_slug)
        if (agent && agent.slug !== selectedAgent?.slug) {
          setSelectedAgent(agent)
          setSelectedModel('')
        }
      })
      .catch(() => undefined)
  }, [activeSessionId, agents, selectedAgent?.slug, setSelectedAgent])

  const chatKey = chatContextKey
  const displayError =
    sessionError || agentsError || projectsError || tasksError
  const selectProject = (project: ProjectConfig | null) => {
    if ((project?.id ?? null) === selectedProjectId) return
    handleContextChange()
    setSelectedProjectId(project?.id ?? null)
    setSelectedTask(null)
    setTaskQuery('')
  }
  const selectAgent = (agent: Agent) => {
    if (agent.slug === selectedAgent?.slug) return
    handleContextChange()
    setSelectedAgent(agent)
    setSelectedModel('')
    setSessionError(null)
  }
  const selectSession = (session: ChatSessionRow) => {
    const agent = agents.find(
      (candidate) => candidate.slug === session.agentSlug,
    )
    if (agent && agent.slug !== selectedAgent?.slug) {
      setSelectedAgent(agent)
      setSelectedModel('')
    }
    handleSelectSession(session.id)
  }
  const selectTask = (task: TaskSearchItem) => {
    if (task.id === selectedTask?.id) return
    handleContextChange()
    setSelectedTask(task)
  }
  const clearTask = () => {
    if (!selectedTask) return
    handleContextChange()
    setSelectedTask(null)
  }

  if (agentsLoading && !selectedAgent) {
    return (
      <div className="flex h-full items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <ChatHeader
        showSidebar={showSidebar}
        onToggleSidebar={() => setShowSidebar((current) => !current)}
        agents={agents}
        selectedAgent={selectedAgent}
        onSelectAgent={selectAgent}
        sessionError={sessionError || projectsError}
        agentsError={agentsError}
        projects={projects}
        selectedProject={selectedProject}
        onSelectProject={selectProject}
        models={catalog.models}
        modelsLoading={catalog.isLoading}
        modelsError={catalog.isError}
        selectedModel={selectedModel}
        onSelectModel={setSelectedModel}
      />

      <div className="flex min-h-0 flex-1">
        {showSidebar ? (
          <ChatSidebar
            activeSessionId={activeSessionId}
            selectedAgent={selectedAgent}
            selectedModel={selectedModel}
            selectedProject={selectedProject}
            selectedTask={selectedTask}
            projectSearch={projectSearch}
            filteredProjects={filteredProjects}
            taskQuery={taskQuery}
            tasksLoading={tasksLoading}
            taskResults={taskResults}
            thinkingLevel={thinkingLevel}
            onNewSession={handleNewSession}
            onResumeSession={() => handleSelectSession(activeSessionId)}
            onSelectSession={selectSession}
            onSelectProject={selectProject}
            onSelectTask={selectTask}
            onProjectSearchChange={setProjectSearch}
            onTaskQueryChange={setTaskQuery}
            onClearTask={clearTask}
            onThinkingLevelChange={setThinkingLevel}
          />
        ) : null}

        <main className="min-h-0 min-w-0 flex-1">
          {selectedAgent ? (
            <ChatPanel
              key={chatKey}
              agent={selectedAgent}
              agentSlug={selectedAgent.slug}
              sessionId={activeSessionId ?? undefined}
              workingDir={selectedProject?.rootPath ?? undefined}
              toolsEnabled
              onSessionCreated={handleSessionCreated}
              onClear={handleNewSession}
              projectId={effectiveProjectId}
              externalId={selectedTask?.id}
              thinkingLevel={thinkingLevel || null}
              model={selectedModel || null}
            />
          ) : (
            <div
              className={cn(
                'flex h-full items-center justify-center text-sm',
                displayError ? 'text-destructive' : 'text-muted-foreground',
              )}
            >
              {displayError ?? 'No agent available'}
            </div>
          )}
        </main>
      </div>
    </div>
  )
}

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center bg-background">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <ChatContent />
    </Suspense>
  )
}
