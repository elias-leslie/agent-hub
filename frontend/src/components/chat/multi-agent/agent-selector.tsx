"use client";

import { useState, useRef, useEffect } from "react";
import { ChevronDown, Users, Cpu, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Agent, AgentProvider } from "./types";

interface AgentSelectorProps {
  agents: Agent[];
  selectedAgent: Agent | "all";
  onSelect: (agent: Agent | "all") => void;
  disabled?: boolean;
  className?: string;
}

const PROVIDER_ICONS: Record<AgentProvider, typeof Cpu> = {
  claude: Cpu,
  gemini: Sparkles,
};

/**
 * AgentSelector - Dropdown to direct messages to specific agents.
 *
 * Design: Refined dropdown with agent badges, supports "all agents" mode
 * for broadcast messages in roundtable discussions.
 */
export function AgentSelector({
  agents,
  selectedAgent,
  onSelect,
  disabled = false,
  className,
}: AgentSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const isAll = selectedAgent === "all";
  const currentAgent = isAll ? null : selectedAgent;

  return (
    <div ref={dropdownRef} className={cn("relative", className)}>
      <button
        type="button"
        onClick={() => !disabled && setIsOpen(!isOpen)}
        disabled={disabled}
        className={cn(
          "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium",
          "border transition-all duration-200",
          "focus:outline-none focus:ring-2 focus:ring-offset-2",
          disabled && "opacity-50 cursor-not-allowed",
          isAll
            ? "bg-slate-100 text-slate-700 border-slate-200 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700 dark:hover:bg-slate-700 focus:ring-slate-400"
            : currentAgent?.provider === "claude"
              ? "bg-orange-50 text-orange-700 border-orange-200 hover:bg-orange-100 dark:bg-orange-950/40 dark:text-orange-300 dark:border-orange-800/50 dark:hover:bg-orange-950/60 focus:ring-orange-400"
              : "bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-800/50 dark:hover:bg-blue-950/60 focus:ring-blue-400"
        )}
      >
        {isAll ? (
          <>
            <Users className="h-4 w-4" />
            <span>All Agents</span>
          </>
        ) : currentAgent ? (
          <>
            {PROVIDER_ICONS[currentAgent.provider] && (
              <span
                className={cn(
                  currentAgent.provider === "claude"
                    ? "text-orange-500 dark:text-orange-400"
                    : "text-blue-500 dark:text-blue-400"
                )}
              >
                {(() => {
                  const Icon = PROVIDER_ICONS[currentAgent.provider];
                  return <Icon className="h-4 w-4" />;
                })()}
              </span>
            )}
            <span>{currentAgent.shortName}</span>
          </>
        ) : null}
        <ChevronDown
          className={cn(
            "h-4 w-4 transition-transform duration-200",
            isOpen && "rotate-180"
          )}
        />
      </button>

      {isOpen && (
        <div
          className={cn(
            "absolute left-0 top-full mt-1.5 min-w-[180px] z-50",
            "rounded-lg border border-slate-200 dark:border-slate-700",
            "bg-white dark:bg-slate-900 shadow-lg",
            "animate-in fade-in-0 zoom-in-95 duration-150"
          )}
        >
          <div className="p-1">
            {/* All Agents option */}
            <button
              type="button"
              onClick={() => {
                onSelect("all");
                setIsOpen(false);
              }}
              className={cn(
                "w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left",
                "transition-colors duration-150",
                isAll
                  ? "bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100"
                  : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50"
              )}
            >
              <Users className="h-4 w-4" />
              <span className="font-medium">All Agents</span>
              <span className="ml-auto text-xs opacity-60">broadcast</span>
            </button>

            <div className="my-1 h-px bg-slate-200 dark:bg-slate-700" />

            {/* Individual agents */}
            {agents.map((agent) => {
              const Icon = PROVIDER_ICONS[agent.provider];
              const isClaude = agent.provider === "claude";
              const isSelected = !isAll && currentAgent?.id === agent.id;

              return (
                <button
                  key={agent.id}
                  type="button"
                  onClick={() => {
                    onSelect(agent);
                    setIsOpen(false);
                  }}
                  className={cn(
                    "w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left",
                    "transition-colors duration-150",
                    isSelected
                      ? isClaude
                        ? "bg-orange-50 dark:bg-orange-950/40 text-orange-700 dark:text-orange-300"
                        : "bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300"
                      : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50"
                  )}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4",
                      isClaude
                        ? "text-orange-500 dark:text-orange-400"
                        : "text-blue-500 dark:text-blue-400"
                    )}
                  />
                  <div className="flex-1">
                    <span className="font-medium">{agent.shortName}</span>
                    {agent.persona && (
                      <span className="ml-1.5 text-xs opacity-60">
                        {agent.persona}
                      </span>
                    )}
                  </div>
                  <span
                    className={cn(
                      "text-xs font-mono",
                      isClaude
                        ? "text-orange-400 dark:text-orange-500"
                        : "text-blue-400 dark:text-blue-500"
                    )}
                  >
                    {agent.provider}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
