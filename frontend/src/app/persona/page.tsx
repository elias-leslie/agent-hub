"use client";

import { useState, useMemo, Suspense } from "react";
import { Loader2, Settings, PanelLeftClose, PanelLeft, FolderOpen, ChevronDown } from "lucide-react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";

import { ChatPanel } from "@/components/chat";
import { SessionSidebar } from "@/components/chat/session-sidebar";
import { useChatSession } from "../chat/hooks/useChatSession";
import { useProjectContext, type ProjectConfig } from "../chat/hooks/useProjectContext";
import { usePersona } from "./hooks/usePersona";

function PersonaContent() {
  const [showSidebar, setShowSidebar] = useState(true);
  const searchParams = useSearchParams();

  const { persona, loading: personaLoading } = usePersona();

  const {
    activeSessionId,
    sidebarRefreshTrigger,
    handleSessionCreated,
    handleSelectSession,
    handleNewSession,
  } = useChatSession();

  const {
    projects,
    selectedProject,
    setSelectedProject,
  } = useProjectContext();

  const [showProjectSelector, setShowProjectSelector] = useState(false);

  // Deep-link support: ?prompt= and ?task= URL params
  const initialPrompt = useMemo(() => {
    const prompt = searchParams.get("prompt");
    const taskId = searchParams.get("task");
    if (prompt) return prompt;
    if (taskId) return `What's the status of task ${taskId}? What happened and what are my options?`;
    return undefined;
  }, [searchParams]);

  if (personaLoading) {
    return (
      <div className="h-full flex items-center justify-center bg-slate-50 dark:bg-slate-950">
        <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="h-full flex bg-slate-50 dark:bg-slate-950">
      {/* Session Sidebar */}
      {showSidebar && (
        <div className="w-64 flex-shrink-0 border-r border-slate-200 dark:border-slate-800">
          <SessionSidebar
            activeSessionId={activeSessionId}
            onSelectSession={handleSelectSession}
            onNewSession={handleNewSession}
            refreshTrigger={sidebarRefreshTrigger}
          />
        </div>
      )}

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="flex-shrink-0 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg z-20 relative">
          <div className="flex items-center justify-between px-4 h-14">
            <div className="flex items-center gap-3">
              {/* Sidebar Toggle */}
              <button
                onClick={() => setShowSidebar(!showSidebar)}
                className="p-1.5 rounded-md text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                title={showSidebar ? "Hide sidebar" : "Show sidebar"}
              >
                {showSidebar ? (
                  <PanelLeftClose className="h-5 w-5" />
                ) : (
                  <PanelLeft className="h-5 w-5" />
                )}
              </button>

              <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                {persona?.name || "Persona"}
              </h1>

              {/* Project Selector */}
              <div className="relative">
                <button
                  onClick={() => setShowProjectSelector(!showProjectSelector)}
                  className={cn(
                    "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium",
                    "bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-400",
                    "hover:bg-indigo-100 dark:hover:bg-indigo-900/40 transition-colors",
                  )}
                >
                  <FolderOpen className="h-3.5 w-3.5" />
                  {selectedProject.name}
                  <ChevronDown className="h-3 w-3" />
                </button>

                {showProjectSelector && (
                  <div className="absolute left-0 top-full mt-1 w-48 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-lg z-50">
                    <div className="p-1">
                      {projects.map((project: ProjectConfig) => (
                        <button
                          key={project.id}
                          onClick={() => {
                            setSelectedProject(project);
                            setShowProjectSelector(false);
                          }}
                          className={cn(
                            "w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left",
                            "hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors",
                            project.id === selectedProject.id &&
                              "bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-400",
                          )}
                        >
                          <FolderOpen className="h-4 w-4 flex-shrink-0" />
                          <span className="flex-1">{project.name}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Settings Gear */}
            <Link
              href="/persona/settings"
              className="p-2 rounded-lg transition-colors text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
              title="Persona settings"
            >
              <Settings className="h-5 w-5" />
            </Link>
          </div>
        </header>

        {/* Chat Area */}
        <main className="flex-1 min-h-0">
          {persona ? (
            <ChatPanel
              key={`${selectedProject.id}-persona`}
              agentSlug={persona.agent_slug}
              sessionId={activeSessionId || undefined}
              workingDir={selectedProject.rootPath}
              toolsEnabled={true}
              onSessionCreated={handleSessionCreated}
              initialPrompt={initialPrompt}
              projectId={selectedProject.id}
            />
          ) : (
            <div className="h-full flex items-center justify-center text-slate-500">
              Persona not configured
            </div>
          )}
        </main>
      </div>

    </div>
  );
}

export default function PersonaPage() {
  return (
    <Suspense
      fallback={
        <div className="h-full flex items-center justify-center bg-slate-50 dark:bg-slate-950">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      }
    >
      <PersonaContent />
    </Suspense>
  );
}
