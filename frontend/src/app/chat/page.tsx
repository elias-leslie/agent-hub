"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  ChevronDown,
  Cpu,
  Server,
  Loader2,
  Paperclip,
  X,
  AlertCircle,
  PanelLeftClose,
  PanelLeft,
} from "lucide-react";

import { ChatPanel } from "@/components/chat";
import { SessionSidebar } from "@/components/chat/session-sidebar";
import { cn } from "@/lib/utils";
import { getApiBaseUrl, fetchApi } from "@/lib/api-config";

import type { Agent } from "@/types/agent";

interface ContextChip {
  id: string;
  type: "file" | "folder" | "url";
  label: string;
  value: string;
}

function ChatContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const sessionIdFromUrl = searchParams.get("session_id");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(sessionIdFromUrl);
  const [showSidebar, setShowSidebar] = useState(true);

  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [showAgentSelector, setShowAgentSelector] = useState(false);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [agentsError, setAgentsError] = useState<string | null>(null);

  const [contextChips, setContextChips] = useState<ContextChip[]>([]);
  const [showContextMenu, setShowContextMenu] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [sidebarRefreshTrigger, setSidebarRefreshTrigger] = useState(0);

  const handleSessionCreated = useCallback((newSessionId: string) => {
    setActiveSessionId(newSessionId);
    router.push(`/chat?session_id=${newSessionId}`, { scroll: false });
    setSidebarRefreshTrigger((prev) => prev + 1);
  }, [router]);

  useEffect(() => {
    const fetchAgents = async () => {
      setAgentsLoading(true);
      setAgentsError(null);
      try {
        const res = await fetchApi(`${getApiBaseUrl()}/api/agents?active_only=true`);
        if (!res.ok) throw new Error(`Failed to fetch agents: ${res.status}`);
        const data = await res.json();
        const fetchedAgents = data.agents;
        setAgents(fetchedAgents);

        // Try to find a good default agent
        // Try to find a good default agent
        if (fetchedAgents.length > 0 && !selectedAgent) {
          const agentSlugFromUrl = searchParams.get("agent");
          let defaultAgent = null;

          if (agentSlugFromUrl) {
            defaultAgent = fetchedAgents.find((a: Agent) => a.slug === agentSlugFromUrl);
          }

          if (!defaultAgent) {
            defaultAgent = fetchedAgents.find((a: Agent) => a.slug === "chat") || fetchedAgents[0];
          }

          setSelectedAgent(defaultAgent);
        }
      } catch (err) {
        setAgentsError(err instanceof Error ? err.message : "Failed to load agents");
      } finally {
        setAgentsLoading(false);
      }
    };
    fetchAgents();
  }, [searchParams]);

  const handleSelectSession = useCallback((sessionId: string | null) => {
    setActiveSessionId(sessionId);
    setSessionError(null);
    if (sessionId) {
      router.push(`/chat?session_id=${sessionId}`, { scroll: false });
    } else {
      router.push("/chat", { scroll: false });
    }
  }, [router]);

  const handleNewSession = useCallback(() => {
    setActiveSessionId(null);
    setSessionError(null);
    router.push("/chat", { scroll: false });
  }, [router]);

  const addContextChip = (type: ContextChip["type"], value: string) => {
    const label = value.split("/").pop() || value;
    const id = `${type}-${Date.now()}`;
    setContextChips((prev) => [...prev, { id, type, label, value }]);
    setShowContextMenu(false);
  };

  const removeContextChip = (id: string) => {
    setContextChips((prev) => prev.filter((c) => c.id !== id));
  };

  const getAgentIcon = (slug: string) => {
    if (slug === "coder" || slug === "refactor") return Cpu;
    return Server;
  };

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
                className={cn(
                  "p-1.5 rounded-md text-slate-500 dark:text-slate-400",
                  "hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                )}
                title={showSidebar ? "Hide sidebar" : "Show sidebar"}
              >
                {showSidebar ? (
                  <PanelLeftClose className="h-5 w-5" />
                ) : (
                  <PanelLeft className="h-5 w-5" />
                )}
              </button>

              <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                Chat
              </h1>

              {/* @mention hint */}
              <span className="text-xs text-slate-400 dark:text-slate-500">
                Select an agent to begin
              </span>
            </div>

            <div className="flex items-center gap-3">
              {/* Agent Selector */}
              {!agentsLoading && selectedAgent && (
                <div className="relative">
                  <button
                    data-testid="model-selector"
                    onClick={() => setShowAgentSelector(!showAgentSelector)}
                    className={cn(
                      "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium",
                      "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300",
                      "hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                    )}
                  >
                    {(() => {
                      const Icon = getAgentIcon(selectedAgent.slug);
                      return <Icon className="h-4 w-4" />;
                    })()}
                    {selectedAgent.name}
                    <ChevronDown className="h-4 w-4" />
                  </button>

                  {showAgentSelector && (
                    <div className="absolute right-0 top-full mt-1 w-56 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-lg z-50 max-h-96 overflow-y-auto">
                      <div className="p-1">
                        {agents.map((agent) => {
                          const Icon = getAgentIcon(agent.slug);
                          return (
                            <button
                              key={agent.slug}
                              onClick={() => {
                                setSelectedAgent(agent);
                                setShowAgentSelector(false);
                              }}
                              className={cn(
                                "w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left",
                                "hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors",
                                agent.slug === selectedAgent.slug && "bg-slate-100 dark:bg-slate-700"
                              )}
                            >
                              <Icon className="h-4 w-4" />
                              <span className="flex-1">{agent.name}</span>
                              <span className="text-xs text-slate-400">{agent.slug}</span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Context Chips Button */}
              <div className="relative">
                <button
                  data-testid="attach-context"
                  onClick={() => setShowContextMenu(!showContextMenu)}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                    contextChips.length > 0
                      ? "bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400"
                      : "bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400",
                    "hover:bg-indigo-200 dark:hover:bg-indigo-900/50"
                  )}
                >
                  <Paperclip className="h-4 w-4" />
                  Attach Context
                  {contextChips.length > 0 && (
                    <span className="ml-1 px-1.5 py-0.5 rounded-full bg-indigo-500 text-white text-xs">
                      {contextChips.length}
                    </span>
                  )}
                </button>

                {showContextMenu && (
                  <div className="absolute right-0 top-full mt-1 w-48 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-lg z-50">
                    <div className="p-1">
                      <button
                        onClick={() => addContextChip("file", "/home/kasadis/agent-hub")}
                        className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left hover:bg-slate-100 dark:hover:bg-slate-700"
                      >
                        Agent Hub
                      </button>
                      <button
                        onClick={() => addContextChip("file", "/home/kasadis/summitflow")}
                        className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left hover:bg-slate-100 dark:hover:bg-slate-700"
                      >
                        SummitFlow
                      </button>
                      <button
                        onClick={() => addContextChip("url", "https://docs.anthropic.com")}
                        className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left hover:bg-slate-100 dark:hover:bg-slate-700"
                      >
                        Anthropic Docs
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Context Chips Display */}
          {contextChips.length > 0 && (
            <div className="border-t border-slate-200 dark:border-slate-800 px-4 py-2 flex flex-wrap gap-2">
              {contextChips.map((chip) => (
                <div
                  key={chip.id}
                  className={cn(
                    "flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium",
                    "bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400"
                  )}
                >
                  <span className="truncate max-w-[120px]">{chip.label}</span>
                  <button
                    onClick={() => removeContextChip(chip.id)}
                    className="p-0.5 rounded hover:bg-indigo-200 dark:hover:bg-indigo-800"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Error Display */}
          {(sessionError || agentsError) && (
            <div className="border-t border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 px-4 py-2">
              <div className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
                <AlertCircle className="h-4 w-4" />
                <span>{sessionError || agentsError}</span>
              </div>
            </div>
          )}
        </header>

        {/* Chat Area */}
        <main className="flex-1 min-h-0">
          {agentsLoading ? (
            <div className="h-full flex items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
            </div>
          ) : selectedAgent ? (
            <ChatPanel
              key={selectedAgent.slug}
              agent={selectedAgent}
              agentSlug={selectedAgent.slug}
              sessionId={activeSessionId || undefined}
              workingDir={contextChips.find((c) => c.type === "folder" || c.type === "file")?.value}
              toolsEnabled={contextChips.some((c) => c.type === "folder" || c.type === "file")}
              onSessionCreated={handleSessionCreated}
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
