"use client";

import { formatDistanceToNowStrict } from "date-fns";
import { ChevronRight, PanelsRightBottom } from "lucide-react";

import { cn } from "@/lib/utils";
import type { SessionListItem } from "@/lib/api/sessions";
import type { PersonaRuntimeState } from "../hooks/usePersonaRuntime";
import type { PersonaOperatorTab } from "./PersonaOperatorDeck";
import { prettifyDisplayText, shortenText } from "./workspace-format";

interface PersonaThreadHeaderProps {
  runtime: PersonaRuntimeState;
  focusSession: SessionListItem | null;
  selectedSessionId: string | null;
  targetProjectId: string;
  threadSource?: "draft" | "session" | null;
  onSelectSession: (sessionId: string | null) => void;
  activeTab: PersonaOperatorTab;
  onOpenTab: (tab: PersonaOperatorTab) => void;
  onNewThread: () => void;
  deskOpen: boolean;
  onToggleDesk: () => void;
  compactViewport?: boolean;
}

function summarize(session: SessionListItem | null, maxLength = 140): string {
  if (!session) {
    return "New instruction";
  }
  const rawSummary = (
    session.live_activity?.summary
    || session.attribution_detail
    || session.attribution_label
    || `Session ${session.id.slice(0, 8)}`
  );
  return shortenText(prettifyDisplayText(rawSummary) || rawSummary, maxLength);
}

function isTerminalPersonaThread(session: SessionListItem | null): boolean {
  if (!session || session.agent_slug !== "persona" || session.parent_session_id) {
    return false;
  }
  if (session.status === "active" || session.live_activity?.status === "active") {
    return false;
  }
  return !["waiting_for_model", "running_tool", "finalizing"].includes(session.live_activity?.phase ?? "");
}

export function PersonaThreadHeader({
  runtime,
  focusSession,
  selectedSessionId,
  targetProjectId,
  threadSource = null,
  onSelectSession,
  onOpenTab,
  onNewThread,
  deskOpen,
  onToggleDesk,
  compactViewport = false,
}: PersonaThreadHeaderProps) {
  const selectedSession = focusSession;
  const currentTool = selectedSession?.live_activity?.current_tool_name ?? selectedSession?.live_activity?.last_tool_name;
  const contextPct =
    selectedSession && runtime.primarySessionDetails?.id === selectedSession.id
      ? runtime.primarySessionDetails.context_usage?.percent_used
      : null;
  const updatedAgo = selectedSession?.updated_at
    ? formatDistanceToNowStrict(new Date(selectedSession.updated_at), { addSuffix: true })
    : null;
  const activeProjectId = selectedSession?.project_id ?? null;
  const mainThreadSelected =
    !selectedSessionId || (selectedSession?.agent_slug === "persona" && !selectedSession?.parent_session_id);
  const terminalPersonaThread = isTerminalPersonaThread(selectedSession);
  const threadLabel = threadSource === "draft"
    ? `draft · ${targetProjectId}`
    : activeProjectId ?? targetProjectId;

  return (
    <div className={cn("border-b border-slate-800/60 bg-slate-950/96 px-4", compactViewport ? "py-2" : "py-2.5")}>
      <div className="mx-auto flex w-full max-w-[110rem] flex-col gap-2.5">
        <div className={cn(compactViewport ? "py-1" : "py-1.5")}>
          <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                <span>{threadLabel}</span>
                {updatedAgo ? (
                  <>
                    <span className="text-slate-700">/</span>
                    <span>{updatedAgo}</span>
                  </>
                ) : null}
                {currentTool ? (
                  <>
                    <span className="text-slate-700">/</span>
                    <span>{currentTool}</span>
                  </>
                ) : null}
                {typeof contextPct === "number" ? (
                  <>
                    <span className="text-slate-700">/</span>
                    <span className={contextPct >= 80 ? "text-amber-200" : undefined}>context {Math.round(contextPct)}%</span>
                  </>
                ) : null}
                {terminalPersonaThread ? <span className="sr-only">terminal persona thread</span> : null}
              </div>
              <h2 className={cn("mt-1 font-semibold tracking-tight text-slate-50", compactViewport ? "text-sm" : "text-base lg:text-lg")}>
                {summarize(selectedSession, compactViewport ? 96 : 140)}
              </h2>
            </div>

            <div className="flex flex-wrap items-center gap-2 xl:justify-end">
              <button
                type="button"
                onClick={onToggleDesk}
                className={cn(
                  "inline-flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/80 font-medium text-slate-200 transition hover:border-slate-700 hover:bg-slate-900 lg:hidden",
                  compactViewport ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm",
                )}
              >
                <PanelsRightBottom className="h-4 w-4" />
                {compactViewport ? "Desk" : deskOpen ? "Hide desk" : "Open desk"}
              </button>
            </div>
          </div>

          <div className={cn("mt-3 flex items-center gap-2 overflow-x-auto", compactViewport ? "pb-0.5" : "pb-1")}>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => onSelectSession(null)}
                className={cn(
                  "inline-flex shrink-0 items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition",
                  mainThreadSelected
                    ? "border-amber-500/30 bg-amber-950/20 text-amber-200"
                    : "border-slate-800 bg-slate-950/70 text-slate-300 hover:border-slate-700 hover:bg-slate-900",
                )}
              >
                main
              </button>
              {runtime.activeChildSessions.map((session) => (
                <button
                  key={session.id}
                  type="button"
                  onClick={() => onSelectSession(session.id)}
                  className={cn(
                    "inline-flex max-w-full shrink-0 items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition",
                    selectedSessionId === session.id
                      ? "border-amber-500/30 bg-amber-950/20 text-amber-200"
                      : "border-slate-800 bg-slate-950/70 text-slate-300 hover:border-slate-700 hover:bg-slate-900",
                  )}
                >
                  <span className={cn("h-2 w-2 rounded-full", session.status === "active" || session.live_activity?.status === "active" ? "bg-emerald-400" : "bg-slate-500")} />
                  <span className="truncate">{session.agent_slug || "lane"}</span>
                  <ChevronRight className="h-3 w-3 opacity-40" />
                </button>
              ))}
              <button
                type="button"
                onClick={onNewThread}
                className="inline-flex shrink-0 items-center gap-2 rounded-full border border-slate-800 bg-slate-950/40 px-3 py-1.5 text-xs font-medium text-slate-400 transition hover:border-slate-700 hover:bg-slate-900 hover:text-slate-100"
              >
                New thread
              </button>
            </div>
            {!mainThreadSelected ? (
              <button
                type="button"
                onClick={() => onOpenTab("lanes")}
                className="rounded-full border border-slate-800 bg-slate-950/70 px-3 py-1.5 text-xs font-medium text-slate-400 transition hover:border-slate-700 hover:bg-slate-900 hover:text-slate-200"
              >
                lanes
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
