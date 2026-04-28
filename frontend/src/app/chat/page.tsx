"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";

import { ChatPanel } from "@/components/chat";
import { cn } from "@/lib/utils";
import { ChatHeader } from "./components/ChatHeader";
import { useAgentSelection } from "./hooks/useAgentSelection";
import { useChatSession } from "./hooks/useChatSession";
import { fetchProjectConfigs, type ProjectConfig } from "./hooks/useProjectContext";

const FALLBACK_PROJECT: ProjectConfig = {
  id: "agent-hub",
  name: "Agent Hub",
  rootPath: "/srv/workspaces/projects/agent-hub",
};

const THINKING_LEVELS = [
  { value: "", label: "Default" },
  { value: "minimal", label: "Minimal" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "ultrathink", label: "Ultrathink" },
];

function ChatContent() {
  const [showSidebar, setShowSidebar] = useState(true);
  const [projects, setProjects] = useState<ProjectConfig[]>([FALLBACK_PROJECT]);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState(FALLBACK_PROJECT.id);
  const [taskId, setTaskId] = useState("");
  const [thinkingLevel, setThinkingLevel] = useState("");

  const {
    agents,
    selectedAgent,
    setSelectedAgent,
    loading: agentsLoading,
    error: agentsError,
  } = useAgentSelection();
  const {
    activeSessionId,
    sessionError,
    setSessionError,
    handleSessionCreated,
    handleSelectSession,
    handleNewSession,
  } = useChatSession();

  useEffect(() => {
    let cancelled = false;
    fetchProjectConfigs()
      .then((fetchedProjects) => {
        if (cancelled) return;
        const nextProjects = fetchedProjects.length > 0 ? fetchedProjects : [FALLBACK_PROJECT];
        setProjects(nextProjects);
        if (!nextProjects.some((project) => project.id === selectedProjectId)) {
          setSelectedProjectId(nextProjects[0]?.id ?? FALLBACK_PROJECT.id);
        }
        setProjectsError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setProjectsError(err instanceof Error ? err.message : "Failed to load projects");
      });
    return () => {
      cancelled = true;
    };
  }, [selectedProjectId]);

  useEffect(() => {
    if (selectedAgent?.thinking_level) {
      setThinkingLevel(selectedAgent.thinking_level);
    }
  }, [selectedAgent?.thinking_level]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? projects[0] ?? FALLBACK_PROJECT,
    [projects, selectedProjectId],
  );

  const chatKey = `${selectedAgent?.slug ?? "loading"}:${selectedProject.id}`;
  const displayError = sessionError || agentsError || projectsError;

  if (agentsLoading && !selectedAgent) {
    return (
      <div className="flex h-full items-center justify-center bg-slate-950">
        <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-950">
      <ChatHeader
        showSidebar={showSidebar}
        onToggleSidebar={() => setShowSidebar((current) => !current)}
        agents={agents}
        selectedAgent={selectedAgent}
        onSelectAgent={(agent) => {
          setSelectedAgent(agent);
          setSessionError(null);
        }}
        sessionError={sessionError || projectsError}
        agentsError={agentsError}
        projects={projects}
        selectedProject={selectedProject}
        onSelectProject={(project) => setSelectedProjectId(project.id)}
      />

      <div className="flex min-h-0 flex-1">
        {showSidebar ? (
          <aside className="hidden w-72 shrink-0 border-r border-slate-800/70 bg-slate-950/90 p-3 md:block">
            <div className="space-y-3">
              <section className="rounded-lg border border-slate-800 bg-slate-900/35 p-3">
                <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-slate-500">Thread</div>
                <div className="mt-2 space-y-2 text-xs text-slate-400">
                  <div className="truncate">session {activeSessionId ? activeSessionId.slice(0, 8) : "new"}</div>
                  <div className="truncate">project {selectedProject.id}</div>
                  <div className="truncate">model {selectedAgent?.primary_model_id ?? "loading"}</div>
                </div>
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    onClick={handleNewSession}
                    className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 transition hover:bg-slate-800"
                  >
                    New
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSelectSession(activeSessionId)}
                    disabled={!activeSessionId}
                    className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-200 transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Resume
                  </button>
                </div>
              </section>

              <section className="rounded-lg border border-slate-800 bg-slate-900/35 p-3">
                <label className="block text-[10px] font-medium uppercase tracking-[0.18em] text-slate-500">
                  Task
                </label>
                <input
                  value={taskId}
                  onChange={(event) => setTaskId(event.target.value)}
                  placeholder="task-..."
                  className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-amber-500/40"
                />
              </section>

              <section className="rounded-lg border border-slate-800 bg-slate-900/35 p-3">
                <label className="block text-[10px] font-medium uppercase tracking-[0.18em] text-slate-500">
                  Thinking
                </label>
                <select
                  value={thinkingLevel}
                  onChange={(event) => setThinkingLevel(event.target.value)}
                  className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-amber-500/40"
                >
                  {THINKING_LEVELS.map((level) => (
                    <option key={level.value || "default"} value={level.value}>
                      {level.label}
                    </option>
                  ))}
                </select>
              </section>
            </div>
          </aside>
        ) : null}

        <main className="min-h-0 min-w-0 flex-1">
          {selectedAgent ? (
            <ChatPanel
              key={chatKey}
              agent={selectedAgent}
              agentSlug={selectedAgent.slug}
              sessionId={activeSessionId ?? undefined}
              workingDir={selectedProject.rootPath ?? undefined}
              toolsEnabled
              onSessionCreated={handleSessionCreated}
              onClear={handleNewSession}
              projectId={selectedProject.id}
              externalId={taskId.trim() || undefined}
              thinkingLevel={thinkingLevel || null}
            />
          ) : (
            <div className={cn("flex h-full items-center justify-center text-sm", displayError ? "text-rose-400" : "text-slate-500")}>
              {displayError ?? "No agent available"}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center bg-slate-950">
          <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
        </div>
      }
    >
      <ChatContent />
    </Suspense>
  );
}
