"use client";

import { useState, useEffect, useRef, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  MessageSquare,
  Users,
  ChevronDown,
  Settings2,
  Cpu,
  Server,
  Send,
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
import {
  type Agent,
  RoundtableTimeline,
  RoundtableControls,
} from "@/components/chat/multi-agent";
import { useRoundtable } from "@/hooks/use-roundtable";
import { getApiBaseUrl, fetchApi } from "@/lib/api-config";

interface ModelOption {
  id: string;
  name: string;
  provider: "claude" | "gemini";
}

interface ContextChip {
  id: string;
  type: "file" | "folder" | "url";
  label: string;
  value: string;
}

function modelToAgent(model: ModelOption): Agent {
  const shortName = model.name.split(" ").slice(-2).join(" ");
  return {
    id: model.id,
    name: model.name,
    shortName,
    provider: model.provider,
    model: model.id,
  };
}

function ChatContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const sessionIdFromUrl = searchParams.get("session_id");
  const [activeSessionId, setActiveSessionId] = useState<string | null>(sessionIdFromUrl);
  const [showSidebar, setShowSidebar] = useState(true);

  const [models, setModels] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState<ModelOption | null>(null);
  const [showModelSelector, setShowModelSelector] = useState(false);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);

  const [contextChips, setContextChips] = useState<ContextChip[]>([]);
  const [showContextMenu, setShowContextMenu] = useState(false);
  const [sessionError, setSessionError] = useState<string | null>(null);

  useEffect(() => {
    const fetchModels = async () => {
      setModelsLoading(true);
      setModelsError(null);
      try {
        const res = await fetchApi(`${getApiBaseUrl()}/api/models`);
        if (!res.ok) throw new Error(`Failed to fetch models: ${res.status}`);
        const data = await res.json();
        const fetchedModels = data.models.map((m: { id: string; name: string; provider: string }) => ({
          id: m.id,
          name: m.name,
          provider: m.provider as "claude" | "gemini",
        }));
        setModels(fetchedModels);
        if (fetchedModels.length > 0 && !selectedModel) {
          setSelectedModel(fetchedModels[0]);
        }
      } catch (err) {
        setModelsError(err instanceof Error ? err.message : "Failed to load models");
        const fallback: ModelOption[] = [
          { id: "claude-sonnet-4-5", name: "Claude Sonnet 4.5", provider: "claude" },
          { id: "claude-haiku-4-5", name: "Claude Haiku 4.5", provider: "claude" },
          { id: "gemini-3-flash-preview", name: "Gemini 3 Flash", provider: "gemini" },
        ];
        setModels(fallback);
        if (!selectedModel) setSelectedModel(fallback[0]);
      } finally {
        setModelsLoading(false);
      }
    };
    fetchModels();
  }, []);

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

  const getModelIcon = (provider: string) => {
    return provider === "claude" ? Cpu : Server;
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
          />
        </div>
      )}

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="flex-shrink-0 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg">
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
                Use @Claude or @Gemini to target
              </span>
            </div>

            <div className="flex items-center gap-3">
              {/* Model Selector */}
              {!modelsLoading && selectedModel && (
                <div className="relative">
                  <button
                    data-testid="model-selector"
                    onClick={() => setShowModelSelector(!showModelSelector)}
                    className={cn(
                      "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium",
                      "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300",
                      "hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                    )}
                  >
                    {(() => {
                      const Icon = getModelIcon(selectedModel.provider);
                      return <Icon className="h-4 w-4" />;
                    })()}
                    {selectedModel.name}
                    <ChevronDown className="h-4 w-4" />
                  </button>

                  {showModelSelector && (
                    <div className="absolute right-0 top-full mt-1 w-56 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-lg z-50">
                      <div className="p-1">
                        {models.map((model) => {
                          const Icon = getModelIcon(model.provider);
                          return (
                            <button
                              key={model.id}
                              onClick={() => {
                                setSelectedModel(model);
                                setShowModelSelector(false);
                              }}
                              className={cn(
                                "w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left",
                                "hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors",
                                model.id === selectedModel.id && "bg-slate-100 dark:bg-slate-700"
                              )}
                            >
                              <Icon className="h-4 w-4" />
                              <span className="flex-1">{model.name}</span>
                              <span className="text-xs text-slate-400">{model.provider}</span>
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
          {(sessionError || modelsError) && (
            <div className="border-t border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 px-4 py-2">
              <div className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
                <AlertCircle className="h-4 w-4" />
                <span>{sessionError || modelsError}</span>
              </div>
            </div>
          )}
        </header>

        {/* Chat Area */}
        <main className="flex-1 min-h-0">
          {modelsLoading ? (
            <div className="h-full flex items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
            </div>
          ) : selectedModel ? (
            <ChatPanel
              key={`${selectedModel.id}-${activeSessionId || "new"}`}
              model={selectedModel.id}
              sessionId={activeSessionId || undefined}
              workingDir={contextChips.find((c) => c.type === "folder" || c.type === "file")?.value}
              toolsEnabled={contextChips.some((c) => c.type === "folder" || c.type === "file")}
            />
          ) : (
            <div className="h-full flex items-center justify-center text-slate-500">
              No models available
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
