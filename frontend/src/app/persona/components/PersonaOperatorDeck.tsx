"use client";

import { useDeferredValue, useEffect, useMemo, useState } from "react";
import {
  Activity,
  CalendarClock,
  Command,
  Layers3,
  Sparkles,
  Waypoints,
} from "lucide-react";

import { useToastActions } from "@/components/error/toast";
import type { Persona } from "@/types/persona";
import type { AgentPreview, PreviewProjectOption } from "@/types/agent-preview";
import type { PersonaPulseMetric, PersonaPulseSummary, PersonaStreamEntry } from "@/lib/api/persona-stream";
import type { Session, SessionListItem } from "@/lib/api/sessions";
import {
  fetchExecutionPermission,
  fetchProjectPermissions,
  type ExecutionPermission,
  type ProjectPermission,
} from "@/lib/api/project-permissions";
import {
  createPersonaAutomation,
  deletePersonaAutomation,
  fetchPersonaAutomations,
  fetchPersonaOperatorPreview,
  triggerPersonaAutomation,
  updatePersonaAutomation,
  type PersonaAutomation,
} from "@/lib/api/persona-operator";
import type { FilterMode } from "./pulse-helpers";
import { PulseOverviewPanels } from "./workspace-cards";
import type { PersonaRuntimeState } from "../hooks/usePersonaRuntime";
import { PersonaAutomationPanel } from "./PersonaAutomationPanel";
import { PersonaBackgroundInbox } from "./PersonaBackgroundInbox";
import { PersonaBlockerPanel } from "./PersonaBlockerPanel";
import { PersonaCommandPalette, type PersonaCommandItem } from "./PersonaCommandPalette";
import { PersonaPromptBudgetPanel } from "./PersonaPromptBudgetPanel";
import { PersonaRunHud } from "./PersonaRunHud";
import { PersonaWorkflowComposer } from "./PersonaWorkflowComposer";

export type PersonaOperatorTab = "workflow" | "insights" | "lanes" | "automations";

interface PersonaOperatorDeckProps {
  persona: Persona;
  personaName: string;
  runtime: PersonaRuntimeState;
  focusSession: SessionListItem | null;
  focusSessionDetails: Session | null;
  onStopFocusSession?: () => void;
  entries: PersonaStreamEntry[];
  pulse: PersonaPulseSummary;
  visiblePulseMetrics: PersonaPulseMetric[];
  activeSessionId: string | null;
  selectedProjectId: string;
  onProjectChange: (projectId: string) => void;
  onSelectSession: (sessionId: string | null) => void;
  sendMessage: (content: string, targetAgents?: string[], sessionIdOverride?: string) => void;
  applyPulseFilter: (mode: FilterMode, anchorEntryId?: string | null) => void;
  inspectAgentPulse: (agentSlug: string) => void;
  activeTab: PersonaOperatorTab;
  onTabChange: (tab: PersonaOperatorTab) => void;
  layout?: "rail" | "stacked";
}

const TAB_META: Array<{
  id: PersonaOperatorTab;
  label: string;
  icon: typeof Waypoints;
  detail: string;
}> = [
  { id: "workflow", label: "Workflow", icon: Waypoints, detail: "Run staged work in the open." },
  { id: "insights", label: "Insights", icon: Sparkles, detail: "Blockers, prompt weight, and friction." },
  { id: "lanes", label: "Lanes", icon: Layers3, detail: "Redirect and inspect side work." },
  { id: "automations", label: "Automations", icon: CalendarClock, detail: "Recurring checks and run-now." },
];

function toProjectOptions(permissions: ProjectPermission[]): PreviewProjectOption[] {
  return permissions
    .filter((permission) => permission.permission_tier !== "off")
    .map((permission) => ({
      id: permission.project_id,
      name: permission.project_id,
      rootPath: permission.root_path,
    }));
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
  layout = "rail",
}: PersonaOperatorDeckProps) {
  const toast = useToastActions();

  const [projectPermissions, setProjectPermissions] = useState<ProjectPermission[]>([]);
  const [executionPermission, setExecutionPermission] = useState<ExecutionPermission | null>(null);
  const [workflowPrompt, setWorkflowPrompt] = useState("");
  const deferredWorkflowPrompt = useDeferredValue(workflowPrompt);
  const [preview, setPreview] = useState<AgentPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<PersonaAutomation[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [savingAutomation, setSavingAutomation] = useState(false);
  const [triggeringJobId, setTriggeringJobId] = useState<string | null>(null);
  const [commandsOpen, setCommandsOpen] = useState(false);

  const projectOptions = useMemo(() => {
    const options = toProjectOptions(projectPermissions);
    return options.length > 0 ? options : [{ id: "agent-hub", name: "agent-hub", rootPath: null }];
  }, [projectPermissions]);
  const selectedProject = useMemo(
    () => projectOptions.find((project) => project.id === selectedProjectId) ?? null,
    [projectOptions, selectedProjectId],
  );
  const selectedProjectPermission = useMemo(
    () => projectPermissions.find((project) => project.project_id === selectedProjectId) ?? null,
    [projectPermissions, selectedProjectId],
  );
  const workflowParentSessionId = useMemo(() => {
    if (focusSession?.agent_slug === "persona" && !focusSession.parent_session_id) {
      return focusSession.id;
    }
    if (runtime.primarySession?.agent_slug === "persona" && !runtime.primarySession.parent_session_id) {
      return runtime.primarySession.id;
    }
    return null;
  }, [focusSession, runtime.primarySession]);

  const loadProjectPermissions = async () => {
    try {
      const permissions = await fetchProjectPermissions();
      setProjectPermissions(permissions);
      if (!permissions.some((permission) => permission.project_id === selectedProjectId)) {
        const fallback = permissions.find((permission) => permission.project_id === "agent-hub") ?? permissions[0];
        if (fallback) {
          onProjectChange(fallback.project_id);
        }
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to load project permissions");
    }
  };

  const loadExecutionPermission = async (projectId: string) => {
    try {
      setExecutionPermission(await fetchExecutionPermission(projectId));
    } catch (err) {
      setExecutionPermission(null);
      toast.error(err instanceof Error ? err.message : "Failed to load execution permission");
    }
  };

  const loadPreview = async (projectId: string, promptInput: string) => {
    try {
      setPreviewLoading(true);
      setPreviewError(null);
      setPreview(
        await fetchPersonaOperatorPreview({
          projectId,
          promptInput: promptInput.trim() || "Summarize operator status, blockers, and next best move.",
          taskType: "chat",
        }),
      );
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : "Failed to load preview");
    } finally {
      setPreviewLoading(false);
    }
  };

  const loadAutomations = async () => {
    try {
      setJobsLoading(true);
      setJobsError(null);
      setJobs(await fetchPersonaAutomations());
    } catch (err) {
      setJobsError(err instanceof Error ? err.message : "Failed to load automations");
    } finally {
      setJobsLoading(false);
    }
  };

  useEffect(() => {
    void loadProjectPermissions();
    void loadAutomations();
  }, []);

  useEffect(() => {
    if (!selectedProjectId) {
      return;
    }
    void loadExecutionPermission(selectedProjectId);
    void loadPreview(selectedProjectId, deferredWorkflowPrompt);
  }, [deferredWorkflowPrompt, selectedProjectId]);

  const refreshEverything = async () => {
    await Promise.allSettled([
      runtime.refresh(),
      loadProjectPermissions(),
      loadExecutionPermission(selectedProjectId),
      loadPreview(selectedProjectId, deferredWorkflowPrompt),
      loadAutomations(),
    ]);
  };

  const askStatus = () => {
    sendMessage("Pause and give concise status: current goal, blocker, active lane, and next move.");
  };

  const commands: PersonaCommandItem[] = [
    {
      id: "status",
      label: "Ask Status",
      description: "Interrupt politely and return current goal, blocker, and next move.",
      run: askStatus,
    },
    {
      id: "revise-plan",
      label: "Revise Plan",
      description: "Request a tighter plan for current work without restarting from scratch.",
      run: () => sendMessage("Revise the current plan. Keep what still holds. Call out only the delta and why."),
    },
    {
      id: "review-work",
      label: "Review Current Work",
      description: "Run a bug-risk review over the current branch or output.",
      run: () => sendMessage("Review current work for defects, regressions, and missing verification. Findings first."),
    },
    {
      id: "show-blockers",
      label: "Summarize Blockers",
      description: "Return exact blocker text, missing capability, and the smallest unblock path.",
      run: () => sendMessage("Summarize exact blockers, missing capabilities, and the smallest unblock path."),
    },
    {
      id: "open-workflow",
      label: "Open Workflow",
      description: "Focus the staged workflow panel.",
      run: () => onTabChange("workflow"),
    },
    {
      id: "open-lanes",
      label: "Open Lanes",
      description: "Focus active and blocked lane management.",
      run: () => onTabChange("lanes"),
    },
    {
      id: "open-automations",
      label: "Open Automations",
      description: "Focus scheduled automations.",
      run: () => onTabChange("automations"),
    },
  ];

  const saveAutomation = async (
    jobId: string | null,
    payload: {
      name: string;
      schedule_type: "at" | "every" | "cron";
      schedule_value: string;
      payload_message: string;
    },
  ) => {
    try {
      setSavingAutomation(true);
      if (jobId) {
        await updatePersonaAutomation(jobId, payload);
      } else {
        await createPersonaAutomation(payload);
      }
      await loadAutomations();
      toast.success(jobId ? "Automation updated" : "Automation created");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save automation");
    } finally {
      setSavingAutomation(false);
    }
  };

  const toggleAutomation = async (job: PersonaAutomation) => {
    try {
      setSavingAutomation(true);
      await updatePersonaAutomation(job.id, { enabled: !job.enabled });
      await loadAutomations();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update automation");
    } finally {
      setSavingAutomation(false);
    }
  };

  const removeAutomation = async (jobId: string) => {
    try {
      setSavingAutomation(true);
      await deletePersonaAutomation(jobId);
      await loadAutomations();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete automation");
    } finally {
      setSavingAutomation(false);
    }
  };

  const runAutomationNow = async (job: PersonaAutomation) => {
    try {
      setTriggeringJobId(job.id);
      const result = await triggerPersonaAutomation(job.id);
      await Promise.allSettled([loadAutomations(), runtime.refresh()]);
      if (result.session_id) {
        onSelectSession(result.session_id);
        onTabChange("lanes");
      }
      toast.success(result.session_id ? "Automation running in thread" : "Automation triggered");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to run automation");
    } finally {
      setTriggeringJobId(null);
    }
  };

  const panelChrome = layout === "rail"
    ? "flex h-full min-h-0 flex-col overflow-hidden bg-[#07090d]"
    : "rounded-[24px] border border-slate-800/70 bg-[#07090d] shadow-[0_16px_40px_-28px_rgba(15,23,42,0.95)]";

  const bodyChrome = layout === "rail"
    ? "min-h-0 flex-1 overflow-y-auto px-3 pb-3"
    : "px-3 pb-3";

  const showAllSections = layout === "rail";

  return (
    <div className={panelChrome} data-testid="persona-operator-deck">
      <div className="border-b border-slate-800/60 px-3 py-3">
        <PersonaRunHud
          personaName={personaName}
          runtime={runtime}
          session={focusSession}
          sessionDetails={focusSessionDetails}
          onStop={() => {
            if (onStopFocusSession) {
              onStopFocusSession();
              return;
            }
            if (!focusSession) {
              void runtime.stopCurrentStream();
              return;
            }
            void runtime.stopSession(focusSession.id);
          }}
          onRefresh={() => void refreshEverything()}
          onOpenCommands={() => setCommandsOpen(true)}
          compact
        />

        <div className="mt-3 flex items-center gap-2 overflow-x-auto pb-1">
          {TAB_META.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => onTabChange(tab.id)}
                className={
                  activeTab === tab.id
                    ? "inline-flex shrink-0 items-center gap-2 rounded-full border border-sky-500/20 bg-sky-950/20 px-3 py-1.5 text-xs font-medium text-sky-100"
                    : "inline-flex shrink-0 items-center gap-2 rounded-full border border-slate-800/70 bg-slate-950/70 px-3 py-1.5 text-xs font-medium text-slate-300 transition hover:border-slate-700 hover:bg-slate-900"
                }
                title={tab.detail}
              >
                <Icon className="h-3.5 w-3.5" />
                {tab.label}
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => setCommandsOpen(true)}
            className="inline-flex shrink-0 items-center gap-2 rounded-full border border-slate-700 bg-slate-950/70 px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-900"
          >
            <Command className="h-3.5 w-3.5" />
            Commands
          </button>
        </div>
      </div>

      <div className={bodyChrome}>
        <div className="space-y-3 pt-3">
          {showAllSections || activeTab === "workflow" ? (
            <PersonaWorkflowComposer
              projectOptions={projectOptions}
              selectedProjectId={selectedProjectId}
              parentSessionId={workflowParentSessionId}
              onProjectChange={onProjectChange}
              onPromptChange={setWorkflowPrompt}
            />
          ) : null}

          {showAllSections || activeTab === "insights" ? (
            <>
              <PersonaBlockerPanel
                executionState={persona.execution_state}
                heartbeatIntervalMinutes={persona.heartbeat_interval_minutes}
                selectedProject={selectedProjectPermission}
                executionPermission={executionPermission}
                runtime={runtime}
                pulse={pulse}
                preview={preview}
                previewLoading={previewLoading}
                onAskStatus={askStatus}
                onRefresh={() => void refreshEverything()}
              />
              <section className="rounded-[28px] border border-slate-800/70 bg-slate-900/80 p-4">
                <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  <Activity className="h-3.5 w-3.5 text-sky-300" />
                  Feed health
                </div>
                <div className="mt-3">
                  <PulseOverviewPanels
                    visiblePulseMetrics={visiblePulseMetrics}
                    pulse={pulse}
                    applyPulseFilter={applyPulseFilter}
                    inspectAgentPulse={inspectAgentPulse}
                  />
                </div>
              </section>
              <PersonaPromptBudgetPanel
                preview={preview}
                loading={previewLoading}
                error={previewError}
                runtimeContext={focusSessionDetails?.context_usage ?? null}
              />
            </>
          ) : null}

          {showAllSections || activeTab === "lanes" ? (
            <PersonaBackgroundInbox
              entries={entries}
              activeChildSessions={runtime.activeChildSessions}
              activeSessionId={activeSessionId}
              stoppingSessionId={runtime.stoppingSessionId}
              onSelectSession={(sessionId) => onSelectSession(sessionId)}
              onStopSession={(sessionId) => {
                void runtime.stopSession(sessionId);
              }}
              onRedirectSession={(sessionId, draft) => {
                onSelectSession(sessionId);
                sendMessage(draft, undefined, sessionId);
              }}
              onPromoteSession={(sessionId, draft) => {
                onSelectSession(sessionId);
                sendMessage(draft, undefined, sessionId);
              }}
              onHandoffSession={(sessionId, draft) => {
                onSelectSession(sessionId);
                sendMessage(draft, undefined, sessionId);
              }}
            />
          ) : null}

          {showAllSections || activeTab === "automations" ? (
            <PersonaAutomationPanel
              selectedProject={selectedProject}
              jobs={jobs}
              loading={jobsLoading}
              error={jobsError}
              saving={savingAutomation}
              triggeringJobId={triggeringJobId}
              onSave={saveAutomation}
              onToggle={toggleAutomation}
              onDelete={removeAutomation}
              onTrigger={runAutomationNow}
            />
          ) : null}
        </div>
      </div>

      <PersonaCommandPalette
        open={commandsOpen}
        onClose={() => setCommandsOpen(false)}
        commands={commands}
      />
    </div>
  );
}
