"use client";

import { useState } from "react";
import {
  ChevronDown,
  Cpu,
  Server,
  Paperclip,
  X,
  AlertCircle,
  PanelLeftClose,
  PanelLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Agent } from "@/types/agent";
import type { ContextChip } from "../hooks/useContextChips";

interface ChatHeaderProps {
  showSidebar: boolean;
  onToggleSidebar: () => void;
  agents: Agent[];
  selectedAgent: Agent | null;
  onSelectAgent: (agent: Agent) => void;
  contextChips: ContextChip[];
  onAddContextChip: (type: ContextChip["type"], value: string) => void;
  onRemoveContextChip: (id: string) => void;
  sessionError: string | null;
  agentsError: string | null;
}

function getAgentIcon(slug: string) {
  if (slug === "coder" || slug === "refactor") return Cpu;
  return Server;
}

export function ChatHeader({
  showSidebar,
  onToggleSidebar,
  agents,
  selectedAgent,
  onSelectAgent,
  contextChips,
  onAddContextChip,
  onRemoveContextChip,
  sessionError,
  agentsError,
}: ChatHeaderProps) {
  const [showAgentSelector, setShowAgentSelector] = useState(false);
  const [showContextMenu, setShowContextMenu] = useState(false);

  return (
    <header className="flex-shrink-0 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg z-20 relative">
      <div className="flex items-center justify-between px-4 h-14">
        <div className="flex items-center gap-3">
          {/* Sidebar Toggle */}
          <button
            onClick={onToggleSidebar}
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

          <span className="text-xs text-slate-400 dark:text-slate-500">
            Select an agent to begin
          </span>
        </div>

        <div className="flex items-center gap-3">
          {/* Agent Selector */}
          {selectedAgent && (
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
                            onSelectAgent(agent);
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
                    onClick={() => {
                      onAddContextChip("file", "/home/kasadis/agent-hub");
                      setShowContextMenu(false);
                    }}
                    className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left hover:bg-slate-100 dark:hover:bg-slate-700"
                  >
                    Agent Hub
                  </button>
                  <button
                    onClick={() => {
                      onAddContextChip("file", "/home/kasadis/summitflow");
                      setShowContextMenu(false);
                    }}
                    className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left hover:bg-slate-100 dark:hover:bg-slate-700"
                  >
                    SummitFlow
                  </button>
                  <button
                    onClick={() => {
                      onAddContextChip("url", "https://docs.anthropic.com");
                      setShowContextMenu(false);
                    }}
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
                onClick={() => onRemoveContextChip(chip.id)}
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
  );
}
