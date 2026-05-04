'use client'

import {
  Bot,
  Columns2,
  Grid2X2,
  Maximize2,
  MessageSquarePlus,
  PanelRightClose,
  Pause,
  Play,
  Rows2,
  SquareSplitHorizontal,
  StopCircle,
  X,
} from 'lucide-react'
import { useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useMemo, useState } from 'react'

import { ChatPanel } from '@/components/chat'
import {
  cancelSessionStream,
  closeSession,
  fetchSessions,
  type SessionListItem,
} from '@/lib/api/sessions'
import { searchTasks, type TaskSearchItem } from '@/lib/api/tasks'
import {
  type ActionRequest,
  fetchActionRequests,
  upsertWorkChatBinding,
} from '@/lib/api/work-chats'
import { cn } from '@/lib/utils'
import type { Agent } from '@/types/agent'
import { useAgentSelection } from '../chat/hooks/useAgentSelection'
import {
  fetchProjectConfigs,
  type ProjectConfig,
} from '../chat/hooks/useProjectContext'

type WorkChatLayout =
  | 'horizontal'
  | 'vertical'
  | 'main-side'
  | 'two-by-two'
  | 'wide-grid'

interface WorkChatPane {
  id: string
  sessionId: string | null
  agentSlug: string
  projectId: string | null
  taskId: string | null
  taskTitle: string | null
  feedbackId: string | null
  designId: string | null
  thinkingLevel: string
}

interface WorkStartCommand {
  key: number
  prompt: string
}

const STORAGE_KEY = 'agent_hub_work_chats_v1'
const MAX_PANES = 6
const FALLBACK_PROJECT: ProjectConfig = {
  id: 'agent-hub',
  name: 'Agent Hub',
  rootPath: '/srv/workspaces/projects/agent-hub',
}

function paneId() {
  return `pane-${Math.random().toString(36).slice(2, 10)}`
}

function makePane(agentSlug = 'chat'): WorkChatPane {
  return {
    id: paneId(),
    sessionId: null,
    agentSlug,
    projectId: null,
    taskId: null,
    taskTitle: null,
    feedbackId: null,
    designId: null,
    thinkingLevel: '',
  }
}

function readSavedState(defaultAgent: string): {
  layout: WorkChatLayout
  activePaneId: string
  panes: WorkChatPane[]
} {
  if (typeof window === 'undefined') {
    const pane = makePane(defaultAgent)
    return { layout: 'main-side', activePaneId: pane.id, panes: [pane] }
  }
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) {
    const pane = makePane(defaultAgent)
    return { layout: 'main-side', activePaneId: pane.id, panes: [pane] }
  }
  try {
    const parsed = JSON.parse(raw)
    const panes = Array.isArray(parsed.panes)
      ? parsed.panes
          .slice(0, MAX_PANES)
          .filter((pane: WorkChatPane) => pane?.id)
      : []
    if (panes.length === 0) throw new Error('empty panes')
    return {
      layout: parsed.layout ?? 'main-side',
      activePaneId: parsed.activePaneId ?? panes[0].id,
      panes,
    }
  } catch {
    const pane = makePane(defaultAgent)
    return { layout: 'main-side', activePaneId: pane.id, panes: [pane] }
  }
}

function layoutClass(layout: WorkChatLayout, count: number) {
  if (count === 1) return 'grid-cols-1'
  switch (layout) {
    case 'horizontal':
      return 'grid-cols-1'
    case 'vertical':
      return 'grid-cols-2'
    case 'two-by-two':
      return 'grid-cols-2'
    case 'wide-grid':
      return 'grid-cols-3'
    case 'main-side':
      return 'grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]'
  }
}

function workContextForPane(pane: WorkChatPane, project: ProjectConfig | null) {
  return {
    mode: pane.taskId
      ? 'project_task'
      : pane.projectId
        ? 'project'
        : pane.feedbackId || pane.designId
          ? 'artifact'
          : 'general',
    project_id: pane.projectId ?? undefined,
    project_name: project?.name,
    task_id: pane.taskId ?? undefined,
    task_title: pane.taskTitle ?? undefined,
    feedback_id: pane.feedbackId ?? undefined,
    design_id: pane.designId ?? undefined,
    surface: 'work_chats',
    pane_id: pane.id,
  }
}

function startPromptForPane(
  pane: WorkChatPane,
  project: ProjectConfig | null,
): string {
  const lines = [
    'Start work in this Work Chats pane.',
    'Use the injected work_context as authoritative. Keep this parent chat as supervisor context and spawn child work lanes for implementation when useful.',
  ]
  if (pane.taskId) {
    lines.push(
      `Work task ${pane.taskId}${pane.taskTitle ? `: ${pane.taskTitle}` : ''}.`,
    )
  } else if (pane.projectId) {
    lines.push(
      `Work in project ${project?.name ?? pane.projectId}. Create or link a task before implementation if one is needed.`,
    )
  } else if (pane.feedbackId || pane.designId) {
    lines.push(
      'Create or link the relevant task from the selected artifact, then start work.',
    )
  } else {
    lines.push(
      'General mode: create project/task records first if the work needs durable tracking.',
    )
  }
  return lines.join('\n')
}

function LayoutButton({
  value,
  active,
  onClick,
}: {
  value: WorkChatLayout
  active: boolean
  onClick: () => void
}) {
  const Icon =
    value === 'horizontal'
      ? Rows2
      : value === 'vertical'
        ? Columns2
        : value === 'two-by-two'
          ? Grid2X2
          : value === 'wide-grid'
            ? SquareSplitHorizontal
            : PanelRightClose
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex h-8 w-8 items-center justify-center rounded-md border transition',
        active
          ? 'border-amber-400/30 bg-amber-500/10 text-amber-200'
          : 'border-border bg-background text-muted-foreground hover:text-foreground',
      )}
      title={value}
    >
      <Icon className="h-4 w-4" />
    </button>
  )
}

function PaneToolbar({
  pane,
  agents,
  sessions,
  projects,
  onPatch,
  onNewChat,
  onSplit,
  onClose,
  onStart,
  onPause,
  onStop,
}: {
  pane: WorkChatPane
  agents: Agent[]
  sessions: SessionListItem[]
  projects: ProjectConfig[]
  onPatch: (patch: Partial<WorkChatPane>) => void
  onNewChat: () => void
  onSplit: () => void
  onClose: () => void
  onStart: () => void
  onPause: () => void
  onStop: () => void
}) {
  const [taskQuery, setTaskQuery] = useState('')
  const [tasks, setTasks] = useState<TaskSearchItem[]>([])

  useEffect(() => {
    if (!pane.projectId) {
      setTasks([])
      return
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      searchTasks({
        projectId: pane.projectId as string,
        query: taskQuery,
        status: null,
        limit: 20,
      })
        .then((result) => {
          if (!cancelled) setTasks(result.tasks)
        })
        .catch(() => {
          if (!cancelled) setTasks([])
        })
    }, 180)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [pane.projectId, taskQuery])

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border bg-card/50 px-2 py-2">
      <button
        type="button"
        onClick={onNewChat}
        title="New Chat"
        className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground transition hover:bg-accent hover:text-foreground"
      >
        <MessageSquarePlus className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={onSplit}
        title="Split Pane"
        className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground transition hover:bg-accent hover:text-foreground"
      >
        <Columns2 className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={() =>
          window.open(`/chat?session_id=${pane.sessionId ?? ''}`, '_blank')
        }
        title="Detach"
        className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground transition hover:bg-accent hover:text-foreground"
      >
        <Maximize2 className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={onStart}
        title={pane.sessionId ? 'Resume Work' : 'Start Work'}
        className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground transition hover:bg-accent hover:text-foreground"
      >
        <Play className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={onPause}
        title="Pause"
        disabled={!pane.sessionId}
        className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground transition hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
      >
        <Pause className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={onStop}
        title="Stop"
        disabled={!pane.sessionId}
        className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground transition hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
      >
        <StopCircle className="h-4 w-4" />
      </button>
      <select
        value={pane.agentSlug}
        onChange={(event) => onPatch({ agentSlug: event.target.value })}
        className="h-8 rounded-md border border-input bg-background px-2 text-xs"
        aria-label="Change Agent"
      >
        {agents.map((agent) => (
          <option key={agent.slug} value={agent.slug}>
            {agent.name} · {agent.slug}
          </option>
        ))}
      </select>
      <select
        value={pane.projectId ?? ''}
        onChange={(event) =>
          onPatch({
            projectId: event.target.value || null,
            taskId: null,
            taskTitle: null,
          })
        }
        className="h-8 rounded-md border border-input bg-background px-2 text-xs"
        aria-label="Change Project Context"
      >
        <option value="">General</option>
        {projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
      <input
        value={taskQuery}
        onChange={(event) => setTaskQuery(event.target.value)}
        placeholder="task..."
        className="h-8 w-28 rounded-md border border-input bg-background px-2 text-xs"
        aria-label="Search Tasks"
      />
      <select
        value={pane.taskId ?? ''}
        onChange={(event) => {
          const task = tasks.find((item) => item.id === event.target.value)
          onPatch({
            taskId: task?.id ?? null,
            taskTitle: task?.title ?? null,
          })
        }}
        className="h-8 rounded-md border border-input bg-background px-2 text-xs"
        aria-label="Change Task Context"
        disabled={!pane.projectId}
      >
        <option value="">No task</option>
        {tasks.map((task) => (
          <option key={task.id} value={task.id}>
            {task.id} · {task.title}
          </option>
        ))}
      </select>
      <select
        value={pane.sessionId ?? ''}
        onChange={(event) => onPatch({ sessionId: event.target.value || null })}
        className="h-8 rounded-md border border-input bg-background px-2 text-xs"
        aria-label="Attach Existing Session"
      >
        <option value="">New session</option>
        {sessions.map((session) => (
          <option key={session.id} value={session.id}>
            {session.id.slice(0, 8)} · {session.agent_slug ?? 'agent'}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={onClose}
        title="Close Pane"
        className="flex h-8 w-8 items-center justify-center rounded-md border border-border bg-background text-muted-foreground transition hover:bg-accent hover:text-foreground ml-auto"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
}

function RightRail({
  sessionId,
  childSessions,
  actionRequests,
}: {
  sessionId: string | null
  childSessions: SessionListItem[]
  actionRequests: ActionRequest[]
}) {
  return (
    <aside className="hidden w-72 shrink-0 border-l border-border bg-card/35 p-3 xl:block">
      <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
        Child Lanes
      </div>
      <div className="mt-2 space-y-2 text-xs">
        {childSessions.length ? (
          childSessions.map((session) => (
            <div
              key={session.id}
              className="rounded-md border border-border bg-background p-2"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium">{session.id.slice(0, 8)}</span>
                <span className="text-muted-foreground">{session.status}</span>
              </div>
              <div className="mt-1 truncate text-muted-foreground">
                {session.summary_oneliner ??
                  session.live_activity?.summary ??
                  'working'}
              </div>
              {session.observed_write_paths?.length ? (
                <div className="mt-1 truncate text-amber-300">
                  {session.observed_write_paths.slice(0, 2).join(', ')}
                </div>
              ) : null}
            </div>
          ))
        ) : (
          <div className="text-muted-foreground">
            {sessionId ? 'No child lanes' : 'No session attached'}
          </div>
        )}
      </div>
      <div className="mt-4 text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
        Action Requests
      </div>
      <div className="mt-2 space-y-2 text-xs">
        {actionRequests.length ? (
          actionRequests.map((request) => (
            <div
              key={request.id}
              className="rounded-md border border-border bg-background p-2"
            >
              <div className="font-medium">{request.request_type}</div>
              <div className="mt-1 text-muted-foreground">
                {request.prompt ?? request.status}
              </div>
              {request.join_code ? (
                <div className="mt-1 font-mono text-amber-300">
                  /join {request.join_code}
                </div>
              ) : null}
            </div>
          ))
        ) : (
          <div className="text-muted-foreground">No blockers</div>
        )}
      </div>
    </aside>
  )
}

function SourceBadges({ pane }: { pane: WorkChatPane }) {
  const badges = ['Web', 'SummitFlow']
  if (pane.sessionId) badges.push('Session')
  if (pane.taskId) badges.push('Task')
  return (
    <div className="flex flex-wrap gap-1">
      {badges.map((badge) => (
        <span
          key={badge}
          className="rounded border border-border bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground"
        >
          {badge}
        </span>
      ))}
    </div>
  )
}

function WorkChatsContent() {
  const searchParams = useSearchParams()
  const queryString = searchParams.toString()
  const { agents, selectedAgent, loading } = useAgentSelection()
  const defaultAgent = selectedAgent?.slug ?? agents[0]?.slug ?? 'chat'
  const [layout, setLayout] = useState<WorkChatLayout>('main-side')
  const [panes, setPanes] = useState<WorkChatPane[]>([])
  const [activePaneId, setActivePaneId] = useState('')
  const [projects, setProjects] = useState<ProjectConfig[]>([FALLBACK_PROJECT])
  const [sessions, setSessions] = useState<SessionListItem[]>([])
  const [childSessions, setChildSessions] = useState<SessionListItem[]>([])
  const [actionRequests, setActionRequests] = useState<ActionRequest[]>([])
  const [startCommands, setStartCommands] = useState<
    Record<string, WorkStartCommand>
  >({})
  const [paneActionError, setPaneActionError] = useState<string | null>(null)
  const [appliedQueryString, setAppliedQueryString] = useState('')

  useEffect(() => {
    const saved = readSavedState(defaultAgent)
    setLayout(saved.layout)
    setPanes(saved.panes)
    setActivePaneId(saved.activePaneId)
  }, [defaultAgent])

  useEffect(() => {
    if (!panes.length) return
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ layout, panes, activePaneId }),
    )
  }, [layout, panes, activePaneId])

  useEffect(() => {
    fetchProjectConfigs()
      .then((items) => setProjects(items.length ? items : [FALLBACK_PROJECT]))
      .catch(() => setProjects([FALLBACK_PROJECT]))
  }, [])

  useEffect(() => {
    if (!queryString || appliedQueryString === queryString || !panes.length) {
      return
    }
    const hasWorkContext =
      searchParams.has('session_id') ||
      searchParams.has('project_id') ||
      searchParams.has('task_id') ||
      searchParams.has('feedback_id') ||
      searchParams.has('design_id')
    if (!hasWorkContext) return

    const queryPane: WorkChatPane = {
      ...makePane(searchParams.get('agent_slug') || defaultAgent),
      sessionId: searchParams.get('session_id'),
      projectId: searchParams.get('project_id'),
      taskId: searchParams.get('task_id'),
      taskTitle: searchParams.get('task_title'),
      feedbackId: searchParams.get('feedback_id'),
      designId: searchParams.get('design_id'),
    }
    setPanes((current) => {
      const emptyIndex = current.findIndex(
        (pane) =>
          !pane.sessionId &&
          !pane.projectId &&
          !pane.taskId &&
          !pane.feedbackId &&
          !pane.designId,
      )
      if (emptyIndex >= 0) {
        const next = [...current]
        next[emptyIndex] = queryPane
        return next
      }
      if (current.length >= MAX_PANES) {
        const replaceIndex = Math.max(
          current.findIndex((pane) => pane.id === activePaneId),
          0,
        )
        const next = [...current]
        next[replaceIndex] = queryPane
        return next
      }
      return [...current, queryPane]
    })
    setActivePaneId(queryPane.id)
    setAppliedQueryString(queryString)
  }, [
    activePaneId,
    appliedQueryString,
    defaultAgent,
    panes.length,
    queryString,
    searchParams,
  ])

  useEffect(() => {
    fetchSessions({ status: 'active', page_size: 100 })
      .then((result) => setSessions(result.sessions))
      .catch(() => setSessions([]))
  }, [panes])

  const activePane = panes.find((pane) => pane.id === activePaneId) ?? panes[0]

  useEffect(() => {
    if (!activePane?.sessionId) {
      setChildSessions([])
      setActionRequests([])
      return
    }
    fetchSessions({ parent_session_id: activePane.sessionId, page_size: 50 })
      .then((result) => setChildSessions(result.sessions))
      .catch(() => setChildSessions([]))
    fetchActionRequests({ session_id: activePane.sessionId })
      .then(setActionRequests)
      .catch(() => setActionRequests([]))
  }, [activePane?.sessionId])

  const visiblePanes = useMemo(
    () =>
      typeof window !== 'undefined' && window.innerWidth < 768 && activePane
        ? [activePane]
        : panes,
    [activePane, panes],
  )

  const patchPane = (paneIdValue: string, patch: Partial<WorkChatPane>) => {
    setPanes((current) =>
      current.map((pane) =>
        pane.id === paneIdValue ? { ...pane, ...patch } : pane,
      ),
    )
  }
  const splitPane = (pane: WorkChatPane) => {
    if (panes.length >= MAX_PANES) return
    const next = { ...pane, id: paneId(), sessionId: null }
    setPanes((current) => [...current, next])
    setActivePaneId(next.id)
  }
  const closePane = (pane: WorkChatPane) => {
    if (panes.length === 1) {
      patchPane(pane.id, { sessionId: null })
      return
    }
    const remaining = panes.filter((item) => item.id !== pane.id)
    setPanes(remaining)
    if (activePaneId === pane.id) setActivePaneId(remaining[0]?.id ?? '')
  }
  const queueStart = (pane: WorkChatPane, project: ProjectConfig | null) => {
    setPaneActionError(null)
    setStartCommands((current) => ({
      ...current,
      [pane.id]: {
        key: Date.now(),
        prompt: startPromptForPane(pane, project),
      },
    }))
  }
  const pausePane = async (pane: WorkChatPane) => {
    if (!pane.sessionId) return
    setPaneActionError(null)
    try {
      await cancelSessionStream(pane.sessionId)
    } catch (error) {
      setPaneActionError(
        error instanceof Error ? error.message : 'Pause failed',
      )
    }
  }
  const stopPane = async (pane: WorkChatPane) => {
    if (!pane.sessionId) return
    setPaneActionError(null)
    try {
      await cancelSessionStream(pane.sessionId).catch(() => null)
      await closeSession(pane.sessionId)
    } catch (error) {
      setPaneActionError(error instanceof Error ? error.message : 'Stop failed')
    }
  }

  if (loading || !panes.length) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        Loading...
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="flex flex-wrap items-center gap-3 border-b border-border bg-card/55 px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Bot className="h-4 w-4 text-amber-300" />
          Work Chats
        </div>
        <div className="flex gap-1">
          {(
            [
              'main-side',
              'horizontal',
              'vertical',
              'two-by-two',
              'wide-grid',
            ] as WorkChatLayout[]
          ).map((item) => (
            <LayoutButton
              key={item}
              value={item}
              active={layout === item}
              onClick={() => setLayout(item)}
            />
          ))}
        </div>
        <select
          value={activePaneId}
          onChange={(event) => setActivePaneId(event.target.value)}
          className="h-8 rounded-md border border-input bg-background px-2 text-xs md:hidden"
          aria-label="Active Pane"
        >
          {panes.map((pane, index) => (
            <option key={pane.id} value={pane.id}>
              Pane {index + 1} · {pane.agentSlug}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => {
            if (panes.length >= MAX_PANES) return
            const next = makePane(defaultAgent)
            setPanes((current) => [...current, next])
            setActivePaneId(next.id)
          }}
          className="ml-auto rounded-md border border-border px-2 py-1 text-xs hover:bg-accent"
        >
          Add Pane
        </button>
        {paneActionError ? (
          <div className="text-xs text-destructive">{paneActionError}</div>
        ) : null}
      </div>
      <div className="flex min-h-0 flex-1">
        <main
          className={cn(
            'grid min-h-0 flex-1 gap-2 p-2',
            layoutClass(layout, visiblePanes.length),
          )}
        >
          {visiblePanes.map((pane, index) => {
            const agent =
              agents.find((item) => item.slug === pane.agentSlug) ?? agents[0]
            const project = pane.projectId
              ? (projects.find((item) => item.id === pane.projectId) ?? null)
              : null
            const context = workContextForPane(pane, project)
            const startCommand = startCommands[pane.id]
            return (
              <section
                key={pane.id}
                onClick={() => setActivePaneId(pane.id)}
                className={cn(
                  'flex min-h-[360px] min-w-0 resize flex-col overflow-hidden rounded-md border bg-background',
                  activePaneId === pane.id
                    ? 'border-amber-400/50'
                    : 'border-border',
                  layout === 'main-side' && index === 0 ? 'md:row-span-2' : '',
                )}
              >
                <PaneToolbar
                  pane={pane}
                  agents={agents}
                  sessions={sessions}
                  projects={projects}
                  onPatch={(patch) => patchPane(pane.id, patch)}
                  onNewChat={() => patchPane(pane.id, { sessionId: null })}
                  onSplit={() => splitPane(pane)}
                  onClose={() => closePane(pane)}
                  onStart={() => queueStart(pane, project)}
                  onPause={() => void pausePane(pane)}
                  onStop={() => void stopPane(pane)}
                />
                <div className="flex flex-wrap items-center gap-2 border-b border-border px-2 py-1 text-xs text-muted-foreground">
                  <SourceBadges pane={pane} />
                  <span>agent {pane.agentSlug}</span>
                  <span>project {pane.projectId ?? 'general'}</span>
                  <span>task {pane.taskId ?? 'none'}</span>
                  <span>
                    session{' '}
                    {pane.sessionId ? pane.sessionId.slice(0, 8) : 'new'}
                  </span>
                </div>
                <div className="min-h-0 flex-1">
                  {agent ? (
                    <ChatPanel
                      key={`${pane.id}:${pane.sessionId ?? 'new'}:${pane.agentSlug}`}
                      agent={agent}
                      agentSlug={pane.agentSlug}
                      sessionId={pane.sessionId ?? undefined}
                      workingDir={project?.rootPath ?? undefined}
                      toolsEnabled
                      projectId={pane.projectId ?? 'agent-hub'}
                      externalId={pane.taskId ?? undefined}
                      sourceMetadata={{
                        transport: 'web',
                        surface: 'work_chats',
                        pane_id: pane.id,
                        source_client: 'agent-hub/work-chats',
                      }}
                      workContext={context}
                      autoSendPrompt={startCommand?.prompt ?? null}
                      autoSendKey={startCommand?.key ?? null}
                      thinkingLevel={pane.thinkingLevel || null}
                      onSessionCreated={(sessionId) => {
                        patchPane(pane.id, { sessionId })
                        void upsertWorkChatBinding({
                          session_id: sessionId,
                          surface: 'work_chats',
                          pane_id: pane.id,
                          project_id: pane.projectId,
                          task_id: pane.taskId,
                          source_client: 'agent-hub/work-chats',
                          work_context: context,
                        })
                      }}
                      onClear={() => patchPane(pane.id, { sessionId: null })}
                    />
                  ) : (
                    <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                      No agent available
                    </div>
                  )}
                </div>
              </section>
            )
          })}
        </main>
        <RightRail
          sessionId={activePane?.sessionId ?? null}
          childSessions={childSessions}
          actionRequests={actionRequests}
        />
      </div>
    </div>
  )
}

export default function WorkChatsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center">
          Loading...
        </div>
      }
    >
      <WorkChatsContent />
    </Suspense>
  )
}
