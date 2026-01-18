"use client";

import { useState, useEffect, useRef } from "react";
import {
  MessageSquare,
  Users,
  ChevronDown,
  Settings2,
  Cpu,
  Server,
  FolderOpen,
  Code2,
  Send,
  Loader2,
} from "lucide-react";

const STORAGE_KEY = "agent-hub-working-dir";

interface ProjectPath {
  name: string;
  path: string;
}

// Default paths always available
const DEFAULT_PATHS: ProjectPath[] = [
  { name: "Home", path: "/home/kasadis" },
  { name: "Agent Hub", path: "/home/kasadis/agent-hub" },
  { name: "SummitFlow", path: "/home/kasadis/summitflow" },
];
import { ChatPanel } from "@/components/chat";
import { cn } from "@/lib/utils";
import {
  type Agent,
  RoundtableTimeline,
  RoundtableControls,
} from "@/components/chat/multi-agent";
import { useRoundtable } from "@/hooks/use-roundtable";
import { getApiBaseUrl } from "@/lib/api-config";

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

  // Coding agent mode state
  const [codingAgentEnabled, setCodingAgentEnabled] = useState(false);
  const [workingDir, setWorkingDir] = useState<string>("");
  const [projectPaths, setProjectPaths] = useState<ProjectPath[]>(DEFAULT_PATHS);
  const [showPathSelector, setShowPathSelector] = useState(false);

  // Load working directory from localStorage and fetch projects
  useEffect(() => {
    // Load saved working directory
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      setWorkingDir(saved);
    }

    // Fetch projects from SummitFlow API (dev only - SummitFlow runs on localhost:8001)
    const fetchProjects = async () => {
      // Only try in dev mode (port 3003)
      if (typeof window !== "undefined" && window.location.port !== "3003") {
        return;
      }
      try {
        const res = await fetch("http://localhost:8001/api/projects");
        if (res.ok) {
          const data = await res.json();
          const apiPaths: ProjectPath[] = data
            .filter((p: { root_path?: string }) => p.root_path)
            .map((p: { name: string; root_path: string }) => ({
              name: p.name,
              path: p.root_path,
            }));

          // Merge with defaults, avoiding duplicates
          const allPaths = [...DEFAULT_PATHS];
          for (const ap of apiPaths) {
            if (!allPaths.some((p) => p.path === ap.path)) {
              allPaths.push(ap);
            }
          }
          setProjectPaths(allPaths);
        }
      } catch {
        // SummitFlow not available, use defaults
      }
    };
    fetchProjects();
  }, []);

  // Save working directory to localStorage when it changes
  useEffect(() => {
    if (workingDir) {
      localStorage.setItem(STORAGE_KEY, workingDir);
    }
  }, [workingDir]);

  const selectPath = (path: string) => {
    setWorkingDir(path);
    setShowPathSelector(false);
  };

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
                  data-testid="model-selector"
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

            {/* Coding Agent Toggle (single mode only) */}
            {mode === "single" && (
              <button
                data-testid="coding-agent-toggle"
                onClick={() => setCodingAgentEnabled(!codingAgentEnabled)}
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors",
                  codingAgentEnabled
                    ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400"
                    : "bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400",
                  "hover:bg-emerald-200 dark:hover:bg-emerald-900/50",
                )}
              >
                <Code2 className="h-4 w-4" />
                Coding Agent
              </button>
            )}

            {/* Settings */}
            <button
              data-testid="roundtable-settings"
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

        {/* Coding Agent Settings Panel */}
        {mode === "single" && codingAgentEnabled && (
          <div className="border-t border-slate-200 dark:border-slate-800 px-4 py-3 bg-emerald-50/50 dark:bg-emerald-950/20">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 text-xs font-medium text-emerald-700 dark:text-emerald-400">
                <FolderOpen className="h-4 w-4" />
                <span>Working Directory:</span>
              </div>

              {/* Project Selector Dropdown */}
              <div className="relative">
                <button
                  data-testid="path-selector"
                  onClick={() => setShowPathSelector(!showPathSelector)}
                  className={cn(
                    "flex items-center gap-2 px-3 py-1.5 rounded-md text-sm",
                    "border border-slate-200 dark:border-slate-700",
                    "bg-white dark:bg-slate-800",
                    "text-slate-700 dark:text-slate-300",
                    "hover:bg-slate-50 dark:hover:bg-slate-700",
                    "transition-colors",
                  )}
                >
                  <span className="max-w-[200px] truncate">
                    {workingDir
                      ? projectPaths.find((p) => p.path === workingDir)?.name ||
                        workingDir.split("/").pop()
                      : "Select project..."}
                  </span>
                  <ChevronDown className="h-4 w-4 flex-shrink-0" />
                </button>

                {showPathSelector && (
                  <div className="absolute left-0 top-full mt-1 w-72 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 shadow-lg z-50 max-h-64 overflow-y-auto">
                    <div className="p-1">
                      {projectPaths.map((project) => (
                        <button
                          key={project.path}
                          onClick={() => selectPath(project.path)}
                          className={cn(
                            "w-full flex flex-col items-start px-3 py-2 rounded-md text-sm text-left",
                            "hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors",
                            project.path === workingDir &&
                              "bg-emerald-50 dark:bg-emerald-900/30",
                          )}
                        >
                          <span className="font-medium text-slate-900 dark:text-slate-100">
                            {project.name}
                          </span>
                          <span className="text-xs text-slate-500 dark:text-slate-400 truncate w-full">
                            {project.path}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Manual path input */}
              <div className="flex-1 max-w-xs">
                <input
                  type="text"
                  data-testid="working-dir-input"
                  value={workingDir}
                  onChange={(e) => setWorkingDir(e.target.value)}
                  placeholder="or enter custom path..."
                  className={cn(
                    "w-full px-3 py-1.5 rounded-md text-sm",
                    "border border-slate-200 dark:border-slate-700",
                    "bg-white dark:bg-slate-800",
                    "text-slate-900 dark:text-slate-100",
                    "placeholder-slate-400 dark:placeholder-slate-500",
                    "focus:outline-none focus:ring-2 focus:ring-emerald-500/50",
                  )}
                />
              </div>

              {workingDir && (
                <span className="text-xs text-emerald-600 dark:text-emerald-400 flex-shrink-0">
                  ✓ Tools enabled
                </span>
              )}
            </div>
          </div>
        )}

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
          <ChatPanel
            key={selectedModel.id} // Force remount on model change to reset chat state
            model={selectedModel.id}
            workingDir={codingAgentEnabled ? workingDir : undefined}
            toolsEnabled={codingAgentEnabled && !!workingDir}
          />
        ) : (
          <RoundtableChat models={roundtableModels} />
        )}
      </main>
    </div>
  );
}


/**
 * Parse @mentions in message text and return detected target.
 * @Claude or @Gemini mentions route to specific agents.
 */
function parseMention(text: string): "claude" | "gemini" | "both" {
  const lowerText = text.toLowerCase();
  const hasClaude = /@claude\b/i.test(text);
  const hasGemini = /@gemini\b/i.test(text);

  if (hasClaude && !hasGemini) return "claude";
  if (hasGemini && !hasClaude) return "gemini";
  return "both";
}

/**
 * Check if cursor is in the middle of typing a mention (e.g., "@Cl")
 */
function getMentionInProgress(text: string, cursorPos: number): string | null {
  // Look backwards from cursor to find @ symbol
  const beforeCursor = text.slice(0, cursorPos);
  const match = beforeCursor.match(/@(\w*)$/);
  if (match) {
    return match[1].toLowerCase();
  }
  return null;
}

// Roundtable chat component - unified timeline with sequential cascade
function RoundtableChat({ models }: { models: ModelOption[] }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [targetAgent, setTargetAgent] = useState<Agent | "all">("all");
  const [toolMode, setToolMode] = useState<"readonly" | "yolo">("readonly");
  const [input, setInput] = useState("");
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const [showMentionMenu, setShowMentionMenu] = useState(false);
  const [mentionFilter, setMentionFilter] = useState("");
  const [cursorPosition, setCursorPosition] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const agents = models.map(modelToAgent);

  // Create session on mount
  useEffect(() => {
    const createSession = async () => {
      if (sessionId) return;
      setIsCreatingSession(true);
      try {
        const res = await fetch(`${getApiBaseUrl()}/api/orchestration/roundtable`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: "agent-hub",
            mode: "quick",
            tools_enabled: true,
          }),
        });
        if (res.ok) {
          const data = await res.json();
          setSessionId(data.id);
        }
      } catch (err) {
        console.error("Failed to create roundtable session:", err);
      } finally {
        setIsCreatingSession(false);
      }
    };
    createSession();
  }, [sessionId]);

  // Use roundtable hook once session is created
  const {
    messages,
    status,
    volleyComplete,
    sendMessage,
    continueDiscussion,
  } = useRoundtable({
    sessionId: sessionId ?? "",
    autoConnect: !!sessionId,
  });

  const isStreaming = status === "streaming";
  const isConnected = status === "connected";
  const canSend = isConnected && input.trim().length > 0 && !isStreaming;

  // Parse @mentions from input to determine effective target
  const mentionTarget = parseMention(input);
  const effectiveTarget =
    mentionTarget !== "both"
      ? mentionTarget
      : targetAgent === "all"
        ? "both"
        : (targetAgent.provider as "claude" | "gemini");

  // Handle input change with mention detection
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    const newCursorPos = e.target.selectionStart ?? 0;
    setInput(newValue);
    setCursorPosition(newCursorPos);

    // Check for mention in progress
    const mentionInProgress = getMentionInProgress(newValue, newCursorPos);
    if (mentionInProgress !== null) {
      setShowMentionMenu(true);
      setMentionFilter(mentionInProgress);
    } else {
      setShowMentionMenu(false);
      setMentionFilter("");
    }
  };

  // Insert mention into text
  const insertMention = (agentName: string) => {
    const beforeCursor = input.slice(0, cursorPosition);
    const afterCursor = input.slice(cursorPosition);

    // Find the @ position
    const atIndex = beforeCursor.lastIndexOf("@");
    if (atIndex === -1) return;

    const newValue = beforeCursor.slice(0, atIndex) + `@${agentName} ` + afterCursor;
    setInput(newValue);
    setShowMentionMenu(false);
    setMentionFilter("");

    // Focus and move cursor
    setTimeout(() => {
      if (textareaRef.current) {
        const newPos = atIndex + agentName.length + 2; // @ + name + space
        textareaRef.current.setSelectionRange(newPos, newPos);
        textareaRef.current.focus();
      }
    }, 0);
  };

  const handleSend = () => {
    if (!canSend) return;
    sendMessage(input.trim(), effectiveTarget);
    setInput("");
    setShowMentionMenu(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Handle mention menu navigation
    if (showMentionMenu) {
      if (e.key === "Escape") {
        e.preventDefault();
        setShowMentionMenu(false);
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && filteredAgents.length > 0)) {
        e.preventDefault();
        if (filteredAgents.length > 0) {
          insertMention(filteredAgents[0].shortName);
        }
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // Filter agents for autocomplete
  const filteredAgents = agents.filter((agent) =>
    agent.shortName.toLowerCase().startsWith(mentionFilter)
  );

  if (isCreatingSession) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
          <Loader2 className="h-5 w-5 animate-spin" />
          <span>Creating roundtable session...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      {/* Unified timeline */}
      <RoundtableTimeline messages={messages} className="flex-1" />

      {/* Controls bar */}
      <RoundtableControls
        toolMode={toolMode}
        onToolModeChange={setToolMode}
        volleyComplete={volleyComplete}
        onContinueDiscussion={continueDiscussion}
        agents={agents}
        selectedTarget={targetAgent}
        onTargetChange={setTargetAgent}
        isStreaming={isStreaming}
      />

      {/* Message input with mention support */}
      <div className="border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
        {/* Target indicator when mention detected */}
        {mentionTarget !== "both" && (
          <div
            className={cn(
              "mb-2 text-xs font-medium flex items-center gap-1.5",
              mentionTarget === "claude"
                ? "text-orange-600 dark:text-orange-400"
                : "text-blue-600 dark:text-blue-400"
            )}
          >
            {mentionTarget === "claude" ? (
              <Cpu className="h-3.5 w-3.5" />
            ) : (
              <Server className="h-3.5 w-3.5" />
            )}
            <span>
              Targeting @{mentionTarget === "claude" ? "Claude" : "Gemini"} only
            </span>
          </div>
        )}

        <div className="relative flex items-end gap-2">
          {/* Mention autocomplete popup */}
          {showMentionMenu && filteredAgents.length > 0 && (
            <div
              data-testid="mention-autocomplete"
              className={cn(
                "absolute left-0 bottom-full mb-1 min-w-[160px] z-50",
                "rounded-lg border border-slate-200 dark:border-slate-700",
                "bg-white dark:bg-slate-900 shadow-lg",
                "animate-in fade-in-0 zoom-in-95 slide-in-from-bottom-2 duration-150"
              )}
            >
              <div className="p-1">
                {filteredAgents.map((agent) => (
                  <button
                    key={agent.id}
                    type="button"
                    onClick={() => insertMention(agent.shortName)}
                    className={cn(
                      "w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left",
                      "transition-colors duration-150",
                      "hover:bg-slate-100 dark:hover:bg-slate-800",
                      agent.provider === "claude"
                        ? "text-orange-700 dark:text-orange-300"
                        : "text-blue-700 dark:text-blue-300"
                    )}
                  >
                    {agent.provider === "claude" ? (
                      <Cpu className="h-4 w-4" />
                    ) : (
                      <Server className="h-4 w-4" />
                    )}
                    <span className="font-medium">@{agent.shortName}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          <textarea
            ref={textareaRef}
            data-testid="roundtable-input"
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder={
              isStreaming
                ? "Waiting for response..."
                : !isConnected
                  ? "Connecting..."
                  : "Type a message... (use @Claude or @Gemini to target)"
            }
            disabled={isStreaming || !isConnected}
            rows={1}
            className={cn(
              "flex-1 resize-none rounded-lg border border-slate-300 dark:border-slate-600",
              "bg-white dark:bg-slate-800 px-4 py-2",
              "focus:outline-none focus:ring-2 focus:ring-indigo-500",
              "disabled:opacity-50 disabled:cursor-not-allowed",
              "min-h-[40px] max-h-[120px]",
            )}
          />
          <button
            data-testid="roundtable-send"
            onClick={handleSend}
            disabled={!canSend}
            className={cn(
              "flex items-center justify-center w-10 h-10 rounded-lg",
              "transition-colors duration-150",
              canSend
                ? "bg-indigo-500 hover:bg-indigo-600 text-white cursor-pointer"
                : "bg-slate-300 dark:bg-slate-600 text-slate-500 cursor-not-allowed",
            )}
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
      </div>
    </div>
  );
}
