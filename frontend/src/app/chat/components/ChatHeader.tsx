"use client";

import { useState } from "react";
import {
  ChevronDown,
  Cpu,
  Server,
  FolderOpen,
  AlertCircle,
  PanelLeftClose,
  PanelLeft,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Agent } from "@/types/agent";
import type { ProjectConfig } from "../hooks/useProjectContext";

interface ChatHeaderProps {
  showSidebar: boolean;
  onToggleSidebar: () => void;
  agents: Agent[];
  selectedAgent: Agent | null;
  onSelectAgent: (agent: Agent) => void;
  sessionError: string | null;
  agentsError: string | null;
  projects: ProjectConfig[];
  selectedProject: ProjectConfig | null;
  onSelectProject: (project: ProjectConfig | null) => void;
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
  sessionError,
  agentsError,
  projects,
  selectedProject,
  onSelectProject,
}: ChatHeaderProps) {
  const [showAgentSelector, setShowAgentSelector] = useState(false);
  const [showProjectSelector, setShowProjectSelector] = useState(false);

  return (
    <header className="flex-shrink-0 border-b border-slate-800 bg-slate-900/80 backdrop-blur-lg z-20 relative">
      <div className="flex items-center justify-between px-4 h-14">
        <div className="flex items-center gap-3">
          {/* Sidebar Toggle */}
          <button
            onClick={onToggleSidebar}
            className={cn(
              "p-1.5 rounded-md text-slate-400",
              "hover:bg-slate-800 transition-colors"
            )}
            title={showSidebar ? "Hide sidebar" : "Show sidebar"}
          >
            {showSidebar ? (
              <PanelLeftClose className="h-5 w-5" />
            ) : (
              <PanelLeft className="h-5 w-5" />
            )}
          </button>

          <h1 className="text-lg font-semibold text-slate-100">
            Chat
          </h1>

          {/* Project Selector */}
          <div className="relative">
            <button
              onClick={() => setShowProjectSelector(!showProjectSelector)}
              className={cn(
                "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium",
                "bg-indigo-900/20 text-indigo-400",
                "hover:bg-indigo-900/40 transition-colors"
              )}
            >
              <FolderOpen className="h-3.5 w-3.5" />
              {selectedProject?.name ?? "General"}
              <ChevronDown className="h-3 w-3" />
            </button>

            {showProjectSelector && (
              <div className="absolute left-0 top-full mt-1 w-48 rounded-lg border border-slate-700 bg-slate-800 shadow-lg z-50">
                <div className="p-1">
                  <button
                    onClick={() => {
                      onSelectProject(null);
                      setShowProjectSelector(false);
                    }}
                    className={cn(
                      "w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left",
                      "hover:bg-slate-700 transition-colors",
                      !selectedProject && "bg-indigo-900/20 text-indigo-400"
                    )}
                  >
                    <FolderOpen className="h-4 w-4 flex-shrink-0" />
                    <span className="flex-1">General</span>
                  </button>
                  {projects.map((project) => (
                    <button
                      key={project.id}
                      onClick={() => {
                        onSelectProject(project);
                        setShowProjectSelector(false);
                      }}
                      className={cn(
                        "w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left",
                        "hover:bg-slate-700 transition-colors",
                        project.id === selectedProject?.id && "bg-indigo-900/20 text-indigo-400"
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

        <div className="flex items-center gap-3">
          {/* Agent Selector */}
          {selectedAgent && (
            <div className="relative">
              <button
                data-testid="model-selector"
                onClick={() => setShowAgentSelector(!showAgentSelector)}
                className={cn(
                  "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium",
                  "bg-slate-800 text-slate-300",
                  "hover:bg-slate-700 transition-colors"
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
                <div className="absolute right-0 top-full mt-1 w-56 rounded-lg border border-slate-700 bg-slate-800 shadow-lg z-50 max-h-96 overflow-y-auto">
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
                            "hover:bg-slate-700 transition-colors",
                            agent.slug === selectedAgent.slug && "bg-slate-700"
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
        </div>
      </div>

      {/* Error Display */}
      {(sessionError || agentsError) && (
        <div className="border-t border-red-800 bg-red-900/20 px-4 py-2">
          <div className="flex items-center gap-2 text-sm text-red-400">
            <AlertCircle className="h-4 w-4" />
            <span>{sessionError || agentsError}</span>
          </div>
        </div>
      )}
    </header>
  );
}
