"use client";

import { useState, useMemo, Suspense } from "react";
import { Loader2 } from "lucide-react";
import { useSearchParams } from "next/navigation";

import { ChatPanel } from "@/components/chat";
import { SessionSidebar } from "@/components/chat/session-sidebar";
import { ChatHeader } from "./components/ChatHeader";
import { useAgentSelection } from "./hooks/useAgentSelection";
import { useChatSession } from "./hooks/useChatSession";
import { useProjectContext } from "./hooks/useProjectContext";

function ChatContent() {
  const [showSidebar, setShowSidebar] = useState(true);
  const searchParams = useSearchParams();

  const {
    agents,
    selectedAgent,
    setSelectedAgent,
    loading: agentsLoading,
    error: agentsError,
  } = useAgentSelection();

  const {
    activeSessionId,
    sidebarRefreshTrigger,
    sessionError,
    setSessionError,
    handleSessionCreated,
    handleSelectSession,
    handleNewSession,
  } = useChatSession();

  const {
    projects,
    selectedProject,
    setSelectedProject,
  } = useProjectContext();

  // Deep-link support: ?prompt= and ?task= URL params
  const initialPrompt = useMemo(() => {
    const prompt = searchParams.get("prompt");
    const taskId = searchParams.get("task");
    if (prompt) return prompt;
    if (taskId) return `What's the status of task ${taskId}? What happened and what are my options?`;
    return undefined;
  }, [searchParams]);

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
        <ChatHeader
          showSidebar={showSidebar}
          onToggleSidebar={() => setShowSidebar(!showSidebar)}
          agents={agents}
          selectedAgent={selectedAgent}
          onSelectAgent={setSelectedAgent}
          sessionError={sessionError}
          agentsError={agentsError}
          projects={projects}
          selectedProject={selectedProject}
          onSelectProject={setSelectedProject}
        />

        {/* Chat Area */}
        <main className="flex-1 min-h-0">
          {agentsLoading ? (
            <div className="h-full flex items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
            </div>
          ) : selectedAgent ? (
            <ChatPanel
              key={`${selectedProject.id}-${selectedAgent.slug}`}
              agent={selectedAgent}
              agentSlug={selectedAgent.slug}
              sessionId={activeSessionId || undefined}
              workingDir={selectedProject.rootPath}
              toolsEnabled={true}
              onSessionCreated={handleSessionCreated}
              initialPrompt={initialPrompt}
              projectId={selectedProject.id}
            />
          ) : (
            <div className="h-full flex items-center justify-center text-slate-500">
              No agents available
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
        <div className="h-full flex items-center justify-center bg-slate-50 dark:bg-slate-950">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      }
    >
      <ChatContent />
    </Suspense>
  );
}
