'use client'

import { Loader2, Search, X } from 'lucide-react'
import { Suspense, useEffect, useMemo, useState } from 'react'

import { ChatPanel } from '@/components/chat'
import { searchTasks, type TaskSearchItem } from '@/lib/api/tasks'
import { cn } from '@/lib/utils'
import type { Agent } from '@/types/agent'
import { ChatHeader } from './components/ChatHeader'
import { useAgentSelection } from './hooks/useAgentSelection'
import { useChatSession } from './hooks/useChatSession'
import {
  fetchProjectConfigs,
  type ProjectConfig,
} from './hooks/useProjectContext'

const FALLBACK_PROJECT: ProjectConfig = {
  id: 'agent-hub',
  name: 'Agent Hub',
  rootPath: '/srv/workspaces/projects/agent-hub',
}

const THINKING_LEVELS = [
  { value: '', label: 'Default' },
  { value: 'minimal', label: 'Minimal' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'ultrathink', label: 'Ultrathink' },
]

function summarizePath(path: string | null): string {
  if (!path) return 'No configured root'
  const parts = path.split('/').filter(Boolean)
  return parts.slice(-2).join(' / ') || path
}

function projectDescription(project: ProjectConfig): string {
  return project.rootPath
    ? summarizePath(project.rootPath)
    : 'General context only'
}

function taskSummary(task: TaskSearchItem): string {
  const prefix = [
    task.id,
    task.priority ? `P${task.priority}` : null,
    task.task_type,
  ]
    .filter(Boolean)
    .join(' · ')
  return `${prefix}: ${task.title}`
}

function ThreadSection({
  activeSessionId,
  selectedProject,
  selectedTask,
  selectedAgent,
  onNewSession,
  onResumeSession,
}: {
  activeSessionId: string | null
  selectedProject: ProjectConfig | null
  selectedTask: TaskSearchItem | null
  selectedAgent: Agent | null
  onNewSession: () => void
  onResumeSession: () => void
}) {
  return (
    <section className="rounded-lg border border-border bg-card/65 p-3">
      <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
        Thread
      </div>
      <div className="mt-2 space-y-2 text-xs text-muted-foreground">
        <div className="truncate">
          session {activeSessionId ? activeSessionId.slice(0, 8) : 'new'}
        </div>
        <div className="truncate">
          context {selectedProject ? selectedProject.id : 'general'}
        </div>
        <div className="truncate">
          task {selectedTask ? selectedTask.id : 'none'}
        </div>
        <div className="truncate">
          model {selectedAgent?.primary_model_id ?? 'loading'}
        </div>
      </div>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={onNewSession}
          className="rounded-md border border-border px-2 py-1 text-xs text-foreground transition hover:bg-accent"
        >
          New
        </button>
        <button
          type="button"
          onClick={onResumeSession}
          disabled={!activeSessionId}
          className="rounded-md border border-border px-2 py-1 text-xs text-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
        >
          Resume
        </button>
      </div>
    </section>
  )
}

function ProjectContextSection({
  selectedProject,
  projectSearch,
  filteredProjects,
  onProjectSearchChange,
  onSelectProject,
  onClearProject,
}: {
  selectedProject: ProjectConfig | null
  projectSearch: string
  filteredProjects: ProjectConfig[]
  onProjectSearchChange: (value: string) => void
  onSelectProject: (project: ProjectConfig | null) => void
  onClearProject: () => void
}) {
  return (
    <section className="rounded-lg border border-border bg-card/65 p-3">
      <div className="flex items-center justify-between gap-2">
        <label className="block text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Project Context
        </label>
        {selectedProject ? (
          <button
            type="button"
            onClick={onClearProject}
            className="text-muted-foreground transition hover:text-foreground"
            title="Clear project context"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>
      <div className="relative mt-2">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <input
          value={projectSearch}
          onChange={(event) => onProjectSearchChange(event.target.value)}
          placeholder="Search projects..."
          className="w-full rounded-md border border-input bg-background py-1.5 pl-7 pr-2 text-xs text-foreground outline-none transition placeholder:text-muted-foreground focus:border-ring focus:ring-2 focus:ring-ring/20"
        />
      </div>
      <div className="mt-2 max-h-36 space-y-1 overflow-y-auto">
        <button
          type="button"
          onClick={() => onSelectProject(null)}
          className={cn(
            'w-full rounded-md px-2 py-1.5 text-left text-xs transition',
            !selectedProject
              ? 'bg-accent text-accent-foreground'
              : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
          )}
        >
          <span className="block font-medium">General chat</span>
          <span className="block truncate text-[11px] opacity-70">
            No repo or task context
          </span>
        </button>
        {filteredProjects.map((project) => (
          <button
            key={project.id}
            type="button"
            onClick={() => onSelectProject(project)}
            className={cn(
              'w-full rounded-md px-2 py-1.5 text-left text-xs transition',
              selectedProject?.id === project.id
                ? 'bg-accent text-accent-foreground'
                : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
            )}
          >
            <span className="block truncate font-medium">{project.name}</span>
            <span className="block truncate text-[11px] opacity-70">
              {project.id} · {projectDescription(project)}
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}

function TaskContextSection({
  selectedProject,
  taskQuery,
  tasksLoading,
  taskResults,
  selectedTask,
  onTaskQueryChange,
  onSelectTask,
  onClearTask,
}: {
  selectedProject: ProjectConfig | null
  taskQuery: string
  tasksLoading: boolean
  taskResults: TaskSearchItem[]
  selectedTask: TaskSearchItem | null
  onTaskQueryChange: (value: string) => void
  onSelectTask: (task: TaskSearchItem) => void
  onClearTask: () => void
}) {
  return (
    <section className="rounded-lg border border-border bg-card/65 p-3">
      <div className="flex items-center justify-between gap-2">
        <label className="block text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
          Task Context
        </label>
        {selectedTask ? (
          <button
            type="button"
            onClick={onClearTask}
            className="text-muted-foreground transition hover:text-foreground"
            title="Clear task context"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </div>
      {selectedProject ? (
        <>
          <div className="relative mt-2">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={taskQuery}
              onChange={(event) => onTaskQueryChange(event.target.value)}
              placeholder="Search task id or title..."
              className="w-full rounded-md border border-input bg-background py-1.5 pl-7 pr-2 text-xs text-foreground outline-none transition placeholder:text-muted-foreground focus:border-ring focus:ring-2 focus:ring-ring/20"
            />
          </div>
          <div className="mt-2 max-h-44 space-y-1 overflow-y-auto">
            {tasksLoading ? (
              <div className="px-2 py-2 text-xs text-muted-foreground">
                Searching...
              </div>
            ) : taskResults.length > 0 ? (
              taskResults.map((task) => (
                <button
                  key={task.id}
                  type="button"
                  onClick={() => onSelectTask(task)}
                  className={cn(
                    'w-full rounded-md px-2 py-1.5 text-left text-xs transition',
                    selectedTask?.id === task.id
                      ? 'bg-accent text-accent-foreground'
                      : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                  )}
                  title={task.description ?? task.title}
                >
                  <span className="block truncate font-medium">
                    {taskSummary(task)}
                  </span>
                  {task.description ? (
                    <span className="block truncate text-[11px] opacity-70">
                      {task.description}
                    </span>
                  ) : null}
                </button>
              ))
            ) : (
              <div className="px-2 py-2 text-xs text-muted-foreground">
                No matching pending tasks
              </div>
            )}
          </div>
        </>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">
          Select a project to search tasks.
        </p>
      )}
    </section>
  )
}

function ThinkingSection({
  thinkingLevel,
  onThinkingLevelChange,
}: {
  thinkingLevel: string
  onThinkingLevelChange: (value: string) => void
}) {
  return (
    <section className="rounded-lg border border-border bg-card/65 p-3">
      <label className="block text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
        Thinking
      </label>
      <select
        value={thinkingLevel}
        onChange={(event) => onThinkingLevelChange(event.target.value)}
        className="mt-2 w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs text-foreground outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/20"
      >
        {THINKING_LEVELS.map((level) => (
          <option key={level.value || 'default'} value={level.value}>
            {level.label}
          </option>
        ))}
      </select>
    </section>
  )
}

function ChatSidebar({
  activeSessionId,
  selectedAgent,
  selectedProject,
  selectedTask,
  projectSearch,
  filteredProjects,
  taskQuery,
  tasksLoading,
  taskResults,
  thinkingLevel,
  onNewSession,
  onResumeSession,
  onSelectProject,
  onSelectTask,
  onProjectSearchChange,
  onTaskQueryChange,
  onClearTask,
  onThinkingLevelChange,
}: {
  activeSessionId: string | null
  selectedAgent: Agent | null
  selectedProject: ProjectConfig | null
  selectedTask: TaskSearchItem | null
  projectSearch: string
  filteredProjects: ProjectConfig[]
  taskQuery: string
  tasksLoading: boolean
  taskResults: TaskSearchItem[]
  thinkingLevel: string
  onNewSession: () => void
  onResumeSession: () => void
  onSelectProject: (project: ProjectConfig | null) => void
  onSelectTask: (task: TaskSearchItem) => void
  onProjectSearchChange: (value: string) => void
  onTaskQueryChange: (value: string) => void
  onClearTask: () => void
  onThinkingLevelChange: (value: string) => void
}) {
  return (
    <aside className="hidden w-72 shrink-0 border-r border-border bg-card/45 p-3 md:block">
      <div className="space-y-3">
        <ThreadSection
          activeSessionId={activeSessionId}
          selectedProject={selectedProject}
          selectedTask={selectedTask}
          selectedAgent={selectedAgent}
          onNewSession={onNewSession}
          onResumeSession={onResumeSession}
        />

        <ProjectContextSection
          selectedProject={selectedProject}
          projectSearch={projectSearch}
          filteredProjects={filteredProjects}
          onProjectSearchChange={onProjectSearchChange}
          onSelectProject={onSelectProject}
          onClearProject={() => onSelectProject(null)}
        />

        <TaskContextSection
          selectedProject={selectedProject}
          taskQuery={taskQuery}
          tasksLoading={tasksLoading}
          taskResults={taskResults}
          selectedTask={selectedTask}
          onTaskQueryChange={onTaskQueryChange}
          onSelectTask={onSelectTask}
          onClearTask={onClearTask}
        />

        <ThinkingSection
          thinkingLevel={thinkingLevel}
          onThinkingLevelChange={onThinkingLevelChange}
        />
      </div>
    </aside>
  )
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
    setSessionError(null)
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
      />

      <div className="flex min-h-0 flex-1">
        {showSidebar ? (
          <ChatSidebar
            activeSessionId={activeSessionId}
            selectedAgent={selectedAgent}
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
