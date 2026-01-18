"use client";

import { useState, useRef, useEffect } from "react";
import {
  PlayCircle,
  Shield,
  ShieldAlert,
  ChevronDown,
  Users,
  Cpu,
  Sparkles,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Agent, AgentProvider } from "./types";

/**
 * Tool mode for roundtable discussions.
 * - readonly: Agents can use Read, Glob, Grep (safe operations)
 * - yolo: Full tool access including Write, Edit, Bash
 */
export type ToolMode = "readonly" | "yolo";

interface RoundtableControlsProps {
  /** Current tool mode */
  toolMode: ToolMode;
  /** Callback when tool mode changes */
  onToolModeChange: (mode: ToolMode) => void;
  /** Whether a volley just completed */
  volleyComplete: boolean;
  /** Callback to continue the discussion */
  onContinueDiscussion: () => void;
  /** Available agents for targeting */
  agents: Agent[];
  /** Currently selected target agent */
  selectedTarget: Agent | "all";
  /** Callback when target changes */
  onTargetChange: (target: Agent | "all") => void;
  /** Whether currently streaming */
  isStreaming?: boolean;
  /** Optional className */
  className?: string;
}

const PROVIDER_ICONS: Record<AgentProvider, typeof Cpu> = {
  claude: Cpu,
  gemini: Sparkles,
};

/**
 * RoundtableControls - Controls for roundtable discussion mode.
 *
 * Design decisions (per task decisions):
 * - d3: Read-only by default with explicit YOLO opt-in
 * - d6: Continue button after each volley
 * - ac-007: @mention routing to specific agents
 */
export function RoundtableControls({
  toolMode,
  onToolModeChange,
  volleyComplete,
  onContinueDiscussion,
  agents,
  selectedTarget,
  onTargetChange,
  isStreaming = false,
  className,
}: RoundtableControlsProps) {
  const [showTargetMenu, setShowTargetMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setShowTargetMenu(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const isAll = selectedTarget === "all";
  const currentAgent = isAll ? null : selectedTarget;

  return (
    <div
      className={cn(
        "flex items-center gap-3 px-4 py-3",
        "border-t border-slate-200 dark:border-slate-800",
        "bg-white dark:bg-slate-900",
        className
      )}
    >
      {/* Tool Mode Toggle */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          data-testid="tool-mode-toggle"
          onClick={() =>
            onToolModeChange(toolMode === "readonly" ? "yolo" : "readonly")
          }
          disabled={isStreaming}
          className={cn(
            "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium",
            "border transition-all duration-200",
            "focus:outline-none focus:ring-2 focus:ring-offset-2",
            isStreaming && "opacity-50 cursor-not-allowed",
            toolMode === "readonly"
              ? "bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800/50 dark:hover:bg-emerald-950/60 focus:ring-emerald-400"
              : "bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-800/50 dark:hover:bg-amber-950/60 focus:ring-amber-400"
          )}
        >
          {toolMode === "readonly" ? (
            <>
              <Shield className="h-4 w-4" />
              <span>Read-only</span>
            </>
          ) : (
            <>
              <ShieldAlert className="h-4 w-4" />
              <span>YOLO Mode</span>
            </>
          )}
        </button>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {toolMode === "readonly"
            ? "Safe: Read, Glob, Grep"
            : "Full access: Write, Edit, Bash"}
        </span>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Agent Target Selector */}
      <div ref={menuRef} className="relative">
        <button
          type="button"
          data-testid="roundtable-target-selector"
          onClick={() => !isStreaming && setShowTargetMenu(!showTargetMenu)}
          disabled={isStreaming}
          className={cn(
            "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium",
            "border transition-all duration-200",
            "focus:outline-none focus:ring-2 focus:ring-offset-2",
            isStreaming && "opacity-50 cursor-not-allowed",
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
              <span>@Both</span>
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
              <span>@{currentAgent.shortName}</span>
            </>
          ) : null}
          <ChevronDown
            className={cn(
              "h-4 w-4 transition-transform duration-200",
              showTargetMenu && "rotate-180"
            )}
          />
        </button>

        {showTargetMenu && (
          <div
            data-testid="roundtable-target-menu"
            className={cn(
              "absolute right-0 bottom-full mb-1.5 min-w-[180px] z-50",
              "rounded-lg border border-slate-200 dark:border-slate-700",
              "bg-white dark:bg-slate-900 shadow-lg",
              "animate-in fade-in-0 zoom-in-95 slide-in-from-bottom-2 duration-150"
            )}
          >
            <div className="p-1">
              {/* All Agents option */}
              <button
                type="button"
                onClick={() => {
                  onTargetChange("all");
                  setShowTargetMenu(false);
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
                <span className="font-medium">@Both</span>
                <span className="ml-auto text-xs opacity-60">all agents</span>
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
                      onTargetChange(agent);
                      setShowTargetMenu(false);
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
                    <span className="font-medium">@{agent.shortName}</span>
                    <span
                      className={cn(
                        "ml-auto text-xs font-mono",
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

      {/* Continue Discussion Button */}
      <button
        type="button"
        data-testid="continue-discussion-btn"
        onClick={onContinueDiscussion}
        disabled={!volleyComplete || isStreaming}
        className={cn(
          "flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium",
          "border transition-all duration-200",
          "focus:outline-none focus:ring-2 focus:ring-offset-2",
          volleyComplete && !isStreaming
            ? "bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100 dark:bg-indigo-950/40 dark:text-indigo-300 dark:border-indigo-800/50 dark:hover:bg-indigo-950/60 focus:ring-indigo-400"
            : "bg-slate-100 text-slate-400 border-slate-200 cursor-not-allowed dark:bg-slate-800 dark:text-slate-500 dark:border-slate-700"
        )}
      >
        {isStreaming ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <PlayCircle className="h-4 w-4" />
        )}
        <span>Continue Discussion</span>
      </button>
    </div>
  );
}
