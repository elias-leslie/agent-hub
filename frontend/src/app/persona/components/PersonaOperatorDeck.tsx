'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'

import type {
  PersonaPulseMetric,
  PersonaPulseSummary,
  PersonaStreamEntry,
} from '@/lib/api/persona-stream'
import type { Session, SessionListItem } from '@/lib/api/sessions'
import type { Persona } from '@/types/persona'
import { usePersonaOperatorData } from '../hooks/usePersonaOperatorData'
import type { PersonaRuntimeState } from '../hooks/usePersonaRuntime'
import { PersonaBackgroundInbox } from './PersonaBackgroundInbox'
import { PersonaBlockerPanel } from './PersonaBlockerPanel'
import {
  type PersonaCommandItem,
  PersonaCommandPalette,
} from './PersonaCommandPalette'
import { PersonaPromptBudgetPanel } from './PersonaPromptBudgetPanel'
import { PersonaRunHud } from './PersonaRunHud'
import { PersonaWorkflowComposer } from './PersonaWorkflowComposer'
import type { FilterMode } from './pulse-helpers'
import { PulseOverviewPanels } from './workspace-cards'

export type PersonaOperatorTab =
  | 'workflow'
  | 'insights'
  | 'lanes'
  | 'automations'

interface PersonaOperatorDeckProps {
  persona: Persona
  personaName: string
  runtime: PersonaRuntimeState
  focusSession: SessionListItem | null
  focusSessionDetails: Session | null
  onStopFocusSession?: () => void
  entries: PersonaStreamEntry[]
  pulse: PersonaPulseSummary
  visiblePulseMetrics: PersonaPulseMetric[]
  activeSessionId: string | null
  selectedProjectId: string
  onProjectChange: (projectId: string) => void
  onSelectSession: (sessionId: string | null) => void
  sendMessage: (
    content: string,
    targetAgents?: string[],
    sessionIdOverride?: string,
  ) => void
  applyPulseFilter: (mode: FilterMode, anchorEntryId?: string | null) => void
  inspectAgentPulse: (agentSlug: string) => void
  activeTab: PersonaOperatorTab
  onTabChange: (tab: PersonaOperatorTab) => void
  layout?: 'rail' | 'stacked'
}

const TAB_META: Array<{
  id: PersonaOperatorTab
  label: string
  detail: string
}> = [
  { id: 'workflow', label: 'Workflow', detail: 'Run staged work in the open.' },
  {
    id: 'insights',
    label: 'Insights',
    detail: 'Blockers, prompt weight, and friction.',
  },
  { id: 'lanes', label: 'Lanes', detail: 'Redirect and inspect side work.' },
  {
    id: 'automations',
    label: 'Automations',
    detail: 'Open scheduled work in Automations.',
  },
]

function buildCommands(
  sendMessage: PersonaOperatorDeckProps['sendMessage'],
  onTabChange: PersonaOperatorDeckProps['onTabChange'],
): PersonaCommandItem[] {
  return [
    {
      id: 'status',
      label: 'Ask Status',
      description:
        'Interrupt politely and return current goal, blocker, and next move.',
      run: () =>
        sendMessage(
          'Pause and give concise status: current goal, blocker, active lane, and next move.',
        ),
    },
    {
      id: 'revise-plan',
      label: 'Revise Plan',
      description:
        'Request a tighter plan for current work without restarting from scratch.',
      run: () =>
        sendMessage(
          'Revise the current plan. Keep what still holds. Call out only the delta and why.',
        ),
    },
    {
      id: 'review-work',
      label: 'Review Current Work',
      description: 'Run a bug-risk review over the current branch or output.',
      run: () =>
        sendMessage(
          'Review current work for defects, regressions, and missing verification. Findings first.',
        ),
    },
    {
      id: 'show-blockers',
      label: 'Summarize Blockers',
      description:
        'Return exact blocker text, missing capability, and the smallest unblock path.',
      run: () =>
        sendMessage(
          'Summarize exact blockers, missing capabilities, and the smallest unblock path.',
        ),
    },
    {
      id: 'open-workflow',
      label: 'Open Workflow',
      description: 'Focus the staged workflow panel.',
      run: () => onTabChange('workflow'),
    },
    {
      id: 'open-lanes',
      label: 'Open Lanes',
      description: 'Focus active and blocked lane management.',
      run: () => onTabChange('lanes'),
    },
    {
      id: 'open-automations',
      label: 'Open Automations',
      description: 'Open the route to scheduled automations.',
      run: () => onTabChange('automations'),
    },
  ]
}

export function PersonaOperatorDeck({
  persona,
  personaName,
  runtime,
  focusSession,
  focusSessionDetails,
  onStopFocusSession,
  entries,
  pulse,
  visiblePulseMetrics,
  activeSessionId,
  selectedProjectId,
  onProjectChange,
  onSelectSession,
  sendMessage,
  applyPulseFilter,
  inspectAgentPulse,
  activeTab,
  onTabChange,
  layout = 'rail',
}: PersonaOperatorDeckProps) {
  const [commandsOpen, setCommandsOpen] = useState(false)

  const {
    projectOptions,
    selectedProjectPermission,
    executionPermission,
    workflowParentSessionId,
    preview,
    previewLoading,
    previewError,
    refreshEverything,
  } = usePersonaOperatorData(
    selectedProjectId,
    onProjectChange,
    focusSession,
    runtime,
  )

  const commands = useMemo(
    () => buildCommands(sendMessage, onTabChange),
    [sendMessage, onTabChange],
  )

  const panelChrome =
    layout === 'rail'
      ? 'flex h-full min-h-0 flex-col overflow-hidden bg-slate-950/90'
      : 'rounded-xl border border-slate-800/60 bg-slate-950/92'

  const bodyChrome =
    layout === 'rail' ? 'min-h-0 flex-1 overflow-y-auto px-3 pb-3' : 'px-3 pb-3'

  const showAllSections = false

  return (
    <div className={panelChrome} data-testid="persona-operator-deck">
      <div className="border-b border-slate-800/50 px-3 py-2.5">
        <PersonaRunHud
          personaName={personaName}
          runtime={runtime}
          session={focusSession}
          sessionDetails={focusSessionDetails}
          onStop={() => {
            if (onStopFocusSession) {
              onStopFocusSession()
              return
            }
            if (!focusSession) {
              void runtime.stopCurrentStream()
              return
            }
            void runtime.stopSession(focusSession.id)
          }}
          onRefresh={() => void refreshEverything()}
          onOpenCommands={() => setCommandsOpen(true)}
          compact
        />

        <div className="mt-2 flex items-center gap-3 overflow-x-auto text-[11px]">
          {TAB_META.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => onTabChange(tab.id)}
              className={
                activeTab === tab.id
                  ? 'shrink-0 border-b border-amber-400 pb-1 font-medium text-slate-100'
                  : 'shrink-0 border-b border-transparent pb-1 text-slate-500 transition hover:text-slate-300'
              }
              title={tab.detail}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className={bodyChrome}>
        <div className="space-y-3 pt-3">
          {showAllSections || activeTab === 'workflow' ? (
            <PersonaWorkflowComposer
              projectOptions={projectOptions}
              selectedProjectId={selectedProjectId}
              parentSessionId={workflowParentSessionId}
              onProjectChange={onProjectChange}
              onPromptChange={() => {
                // Intentionally no-op; prompt state lives in the hook
              }}
            />
          ) : null}

          {showAllSections || activeTab === 'insights' ? (
            <>
              <PersonaBlockerPanel
                executionState={persona.execution_state}
                selectedProject={selectedProjectPermission}
                executionPermission={executionPermission}
                runtime={runtime}
                pulse={pulse}
                preview={preview}
                previewLoading={previewLoading}
                onAskStatus={() =>
                  sendMessage(
                    'Pause and give concise status: current goal, blocker, active lane, and next move.',
                  )
                }
                onRefresh={() => void refreshEverything()}
              />
              <PulseOverviewPanels
                visiblePulseMetrics={visiblePulseMetrics}
                pulse={pulse}
                applyPulseFilter={applyPulseFilter}
                inspectAgentPulse={inspectAgentPulse}
              />
              <PersonaPromptBudgetPanel
                preview={preview}
                loading={previewLoading}
                error={previewError}
                runtimeContext={focusSessionDetails?.context_usage ?? null}
              />
            </>
          ) : null}

          {showAllSections || activeTab === 'lanes' ? (
            <PersonaBackgroundInbox
              entries={entries}
              activeChildSessions={runtime.activeChildSessions}
              activeSessionId={activeSessionId}
              stoppingSessionId={runtime.stoppingSessionId}
              onSelectSession={(sessionId) => onSelectSession(sessionId)}
              onStopSession={(sessionId) => {
                void runtime.stopSession(sessionId)
              }}
              onRedirectSession={(sessionId, draft) => {
                onSelectSession(sessionId)
                sendMessage(draft, undefined, sessionId)
              }}
              onPromoteSession={(sessionId, draft) => {
                onSelectSession(sessionId)
                sendMessage(draft, undefined, sessionId)
              }}
              onHandoffSession={(sessionId, draft) => {
                onSelectSession(sessionId)
                sendMessage(draft, undefined, sessionId)
              }}
            />
          ) : null}

          {showAllSections || activeTab === 'automations' ? (
            <section className="rounded-[28px] border border-slate-800/70 bg-slate-900/80 p-4">
              <h3 className="text-base font-semibold text-slate-100">
                Scheduled persona work
              </h3>
              <p className="mt-2 text-sm text-slate-400">
                Manage persona jobs and check-ins in Automations.
              </p>
              <Link
                href="/automations?project_id=agent-hub"
                className="button-secondary mt-4"
              >
                Open Automations
              </Link>
            </section>
          ) : null}
        </div>
      </div>

      <PersonaCommandPalette
        open={commandsOpen}
        onClose={() => setCommandsOpen(false)}
        commands={commands}
      />
    </div>
  )
}
