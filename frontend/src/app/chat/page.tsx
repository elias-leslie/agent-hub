"use client";

import { useState } from "react";
import {
  MessageSquare,
  Users,
  ChevronDown,
  Settings2,
  Cpu,
  Server,
} from "lucide-react";
import { ChatPanel } from "@/components/chat";
import { cn } from "@/lib/utils";
import {
  AgentSelector,
  TurnIndicator,
  type Agent,
  type AgentTurnState,
} from "@/components/chat/multi-agent";

type ChatMode = "single" | "roundtable";

interface ModelOption {
  id: string;
  name: string;
  provider: "claude" | "gemini";
  icon: typeof Cpu;
}

const MODELS: ModelOption[] = [
  {
    id: "claude-sonnet-4-5-20250514",
    name: "Claude Sonnet 4.5",
    provider: "claude",
    icon: Cpu,
  },
  {
    id: "claude-opus-4-5-20251101",
    name: "Claude Opus 4.5",
    provider: "claude",
    icon: Cpu,
  },
  {
    id: "claude-haiku-4-5-20250514",
    name: "Claude Haiku 4.5",
    provider: "claude",
    icon: Cpu,
  },
  {
    id: "gemini-3-flash-preview",
    name: "Gemini 3 Flash",
    provider: "gemini",
    icon: Server,
  },
  {
    id: "gemini-3-pro-preview",
    name: "Gemini 3 Pro",
    provider: "gemini",
    icon: Server,
  },
];

// Convert ModelOption to Agent for multi-agent components
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

export default function ChatPage() {
  const [mode, setMode] = useState<ChatMode>("single");
  const [selectedModel, setSelectedModel] = useState(MODELS[0]);
  const [roundtableModels, setRoundtableModels] = useState<ModelOption[]>([
    MODELS[0],
    MODELS[3],
  ]);
  const [showModelSelector, setShowModelSelector] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const toggleRoundtableModel = (model: ModelOption) => {
    if (roundtableModels.some((m) => m.id === model.id)) {
      if (roundtableModels.length > 2) {
        setRoundtableModels(roundtableModels.filter((m) => m.id !== model.id));
      }
    } else if (roundtableModels.length < 4) {
      setRoundtableModels([...roundtableModels, model]);
    }
  };

  return (
    <div className="h-full flex flex-col bg-slate-50 dark:bg-slate-950">
      {/* Page Header */}
      <header className="flex-shrink-0 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg">
        <div className="flex items-center justify-between px-6 lg:px-8 h-14">
          <div className="flex items-center gap-4">
            <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              Chat
            </h1>

            {/* Mode Toggle */}
            <div className="flex items-center rounded-lg bg-slate-100 dark:bg-slate-800 p-1">
              <button
                onClick={() => setMode("single")}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                  mode === "single"
                    ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-sm"
                    : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300",
                )}
              >
                <MessageSquare className="h-4 w-4" />
                Single
              </button>
              <button
                onClick={() => setMode("roundtable")}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
                  mode === "roundtable"
                    ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-sm"
                    : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300",
                )}
              >
                <Users className="h-4 w-4" />
                Roundtable
              </button>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Model Selector */}
            {mode === "single" ? (
              <div className="relative">
                <button
                  onClick={() => setShowModelSelector(!showModelSelector)}
                  className={cn(
                    "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium",
                    "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300",
                    "hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors",
                  )}
                >
                  <selectedModel.icon className="h-4 w-4" />
                  {selectedModel.name}
                  <ChevronDown className="h-4 w-4" />
                </button>

                {showModelSelector && (
                  <div className="absolute right-0 top-full mt-1 w-56 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-lg z-50">
                    <div className="p-1">
                      {MODELS.map((model) => (
                        <button
                          key={model.id}
                          onClick={() => {
                            setSelectedModel(model);
                            setShowModelSelector(false);
                          }}
                          className={cn(
                            "w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left",
                            "hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors",
                            model.id === selectedModel.id &&
                              "bg-slate-100 dark:bg-slate-700",
                          )}
                        >
                          <model.icon className="h-4 w-4" />
                          <span className="flex-1">{model.name}</span>
                          <span className="text-xs text-slate-400">
                            {model.provider}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              /* Roundtable: show selected models */
              <div className="flex items-center gap-1">
                {roundtableModels.map((model) => (
                  <div
                    key={model.id}
                    className={cn(
                      "flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium",
                      model.provider === "claude"
                        ? "bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400"
                        : "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400",
                    )}
                  >
                    <model.icon className="h-3 w-3" />
                    {model.name.split(" ").pop()}
                  </div>
                ))}
              </div>
            )}

            {/* Settings */}
            <button
              onClick={() => setShowSettings(!showSettings)}
              className={cn(
                "p-2 rounded-lg text-slate-500 dark:text-slate-400",
                "hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors",
              )}
            >
              <Settings2 className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Roundtable Settings Panel */}
        {mode === "roundtable" && showSettings && (
          <div className="border-t border-slate-200 dark:border-slate-800 px-4 py-3 bg-slate-50 dark:bg-slate-900/50">
            <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-2">
              Select 2-4 models for roundtable discussion:
            </p>
            <div className="flex flex-wrap gap-2">
              {MODELS.map((model) => {
                const isSelected = roundtableModels.some(
                  (m) => m.id === model.id,
                );
                const isDisabled =
                  !isSelected &&
                  (roundtableModels.length >= 4 ||
                    (roundtableModels.length <= 2 &&
                      roundtableModels.some((m) => m.id === model.id)));

                return (
                  <button
                    key={model.id}
                    onClick={() => toggleRoundtableModel(model)}
                    disabled={isDisabled && !isSelected}
                    className={cn(
                      "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                      isSelected
                        ? model.provider === "claude"
                          ? "bg-orange-500 text-white"
                          : "bg-blue-500 text-white"
                        : "bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300",
                      isDisabled &&
                        !isSelected &&
                        "opacity-50 cursor-not-allowed",
                    )}
                  >
                    <model.icon className="h-4 w-4" />
                    {model.name}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </header>

      {/* Chat Area */}
      <main className="flex-1 min-h-0">
        {mode === "single" ? (
          <ChatPanel model={selectedModel.id} />
        ) : (
          <RoundtableChat models={roundtableModels} />
        )}
      </main>
    </div>
  );
}

// Roundtable chat component - shows multiple model responses side by side
function RoundtableChat({ models }: { models: ModelOption[] }) {
  const [targetAgent, setTargetAgent] = useState<Agent | "all">("all");
  const [turnStates, setTurnStates] = useState<AgentTurnState[]>([]);

  const agents = models.map(modelToAgent);

  // Simulate turn state updates (in production, this would come from WebSocket)
  const _handleAgentStateChange = (
    agentId: string,
    state: AgentTurnState["state"],
  ) => {
    setTurnStates((prev) => {
      const existing = prev.find((t) => t.agentId === agentId);
      if (existing) {
        return prev.map((t) =>
          t.agentId === agentId
            ? {
                ...t,
                state,
                startedAt: state !== "idle" ? new Date() : undefined,
              }
            : t,
        );
      }
      return [
        ...prev,
        {
          agentId,
          state,
          startedAt: state !== "idle" ? new Date() : undefined,
        },
      ];
    });
  };

  return (
    <div className="h-full flex flex-col">
      {/* Turn indicator strip */}
      {turnStates.some((t) => t.state !== "idle") && (
        <div className="px-4 py-2 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
          <TurnIndicator agents={agents} turnStates={turnStates} />
        </div>
      )}

      {/* Split view for multiple agents */}
      <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-px bg-slate-200 dark:bg-slate-800 overflow-hidden">
        {models.map((model) => {
          const agent = modelToAgent(model);
          const turnState = turnStates.find((t) => t.agentId === model.id);
          const isActive =
            turnState?.state === "responding" ||
            turnState?.state === "thinking";

          return (
            <div
              key={model.id}
              className={cn(
                "bg-white dark:bg-slate-900 flex flex-col min-h-0 transition-all duration-300",
                isActive && "ring-2 ring-inset",
                isActive && model.provider === "claude" && "ring-orange-400/50",
                isActive && model.provider === "gemini" && "ring-blue-400/50",
              )}
            >
              {/* Agent header */}
              <div
                className={cn(
                  "flex items-center gap-2 px-3 py-2 border-b transition-colors",
                  model.provider === "claude"
                    ? "bg-gradient-to-r from-orange-50 to-amber-50/50 dark:from-orange-950/30 dark:to-amber-950/20 border-orange-200 dark:border-orange-900/50"
                    : "bg-gradient-to-r from-blue-50 to-indigo-50/50 dark:from-blue-950/30 dark:to-indigo-950/20 border-blue-200 dark:border-blue-900/50",
                )}
              >
                <model.icon
                  className={cn(
                    "h-4 w-4",
                    model.provider === "claude"
                      ? "text-orange-600 dark:text-orange-400"
                      : "text-blue-600 dark:text-blue-400",
                  )}
                />
                <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                  {agent.shortName}
                </span>
                {isActive && (
                  <span className="flex items-center gap-1 ml-auto">
                    <span
                      className={cn(
                        "h-2 w-2 rounded-full animate-pulse",
                        model.provider === "claude"
                          ? "bg-orange-500"
                          : "bg-blue-500",
                      )}
                    />
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {turnState?.state}
                    </span>
                  </span>
                )}
              </div>

              {/* Agent chat panel */}
              <div className="flex-1 min-h-0 overflow-hidden">
                <ChatPanel model={model.id} />
              </div>
            </div>
          );
        })}
      </div>

      {/* Shared input with agent selector */}
      <div className="border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-4 py-3">
        <div className="flex items-center gap-3">
          <AgentSelector
            agents={agents}
            selectedAgent={targetAgent}
            onSelect={setTargetAgent}
          />
          <span className="text-sm text-slate-500 dark:text-slate-400">
            {targetAgent === "all"
              ? "Message will be sent to all agents"
              : `Message will be sent to ${targetAgent.shortName}`}
          </span>
        </div>
      </div>
    </div>
  );
}
