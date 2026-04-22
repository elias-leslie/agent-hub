"use client";

import { formatDistanceToNowStrict } from "date-fns";
import { Bot, ChevronRight, PanelsRightBottom } from "lucide-react";

import { cn } from "@/lib/utils";
import type { SessionListItem } from "@/lib/api/sessions";
import type { PersonaRuntimeState } from "../hooks/usePersonaRuntime";
import type { PersonaOperatorTab } from "./PersonaOperatorDeck";
import { prettifyDisplayText, shortenText } from "./workspace-format";
import { CommandSurface, ProvenanceBadge, ScopeChip } from "./persona-operator-chrome";

interface PersonaThreadHeaderProps {
  personaName: string;
  runtime: PersonaRuntimeState;
  focusSession: SessionListItem | null;
  selectedSessionId: string | null;
  targetProjectId: string;
  threadSource?: "draft" | "session" | null;
  onSelectSession: (sessionId: string | null) => void;
  sendMessage: (content: string) => void;
  activeTab: PersonaOperatorTab;
  onOpenTab: (tab: PersonaOperatorTab) => void;
  deskOpen: boolean;
  onToggleDesk: () => void;
  compactViewport?: boolean;
}

function summarize(session: SessionListItem | null, maxLength = 140): string {
  if (!session) {
    return "Fresh thread ready. Draft stays local until persisted.";
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
  personaName,
  runtime,
  focusSession,
  selectedSessionId,
  targetProjectId,
  threadSource = null,
  onSelectSession,
  sendMessage,
  activeTab,
  onOpenTab,
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
  const nextThreadProjectId = activeProjectId && activeProjectId !== targetProjectId ? targetProjectId : null;
  const mainThreadSelected =
    !selectedSessionId || (selectedSession?.agent_slug === "persona" && !selectedSession?.parent_session_id);
  const terminalPersonaThread = isTerminalPersonaThread(selectedSession);
  const effectiveSource = threadSource ?? (selectedSession ? "session" : null);
  const threadLabel = selectedSession?.agent_slug === "persona"
    ? effectiveSource === "draft"
      ? "Draft primary thread"
      : "Persisted primary thread"
    : selectedSession
      ? "Persisted child lane"
      : "Fresh thread";

  return (
    <div className={cn("border-b border-slate-800/60 bg-[linear-gradient(135deg,rgba(15,23,42,0.98),rgba(8,12,19,0.98))] px-4", compactViewport ? "py-2" : "py-2.5")}>
      <div className="mx-auto flex w-full max-w-[110rem] flex-col gap-2.5">
        <CommandSurface className="rounded-[24px]">
          <div className={cn(compactViewport ? "p-3" : "p-4")}>
            <div className={cn("flex flex-col xl:flex-row xl:items-center xl:justify-between", compactViewport ? "gap-2" : "gap-3")}>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="rounded-full border border-sky-500/20 bg-sky-950/20 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-200">
                    Operator thread surface
                  </span>
                  {effectiveSource ? <ProvenanceBadge source={effectiveSource} /> : null}
                  <span className="rounded-full border border-slate-700/80 bg-slate-900/70 px-2.5 py-1 text-[11px] text-slate-300">
                    {threadLabel}
                  </span>
                  <ScopeChip>Desk · {activeTab}</ScopeChip>
                  {updatedAgo ? (
                    <span className="rounded-full border border-slate-800/80 bg-slate-950/70 px-2.5 py-1 text-[11px] text-slate-500">
                      Updated {updatedAgo}
                    </span>
                  ) : null}
                </div>
                <h2 className={cn("line-clamp-1 font-semibold tracking-tight text-slate-50", compactViewport ? "mt-1 text-sm" : "mt-1.5 text-base lg:text-lg")}>
                  {summarize(selectedSession, compactViewport ? 96 : 140)}
                </h2>
                <div className={cn("flex flex-wrap items-center gap-1.5 text-slate-400", compactViewport ? "mt-1 text-[11px]" : "mt-1.5 text-xs")}>
                  {currentTool ? (
                    <span className="rounded-full border border-emerald-500/20 bg-emerald-950/20 px-2.5 py-1 text-emerald-200">
                      Runtime tool · {currentTool}
                    </span>
                  ) : null}
                  {activeProjectId ? (
                    <span className="rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1">
                      Session project · {activeProjectId}
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={() => onOpenTab("workflow")}
                      className="rounded-full border border-sky-500/20 bg-sky-950/20 px-2.5 py-1 text-sky-200 transition hover:border-sky-400/30 hover:bg-sky-950/30"
                    >
                      Next thread target · {targetProjectId}
                    </button>
                  )}
                  {!compactViewport && nextThreadProjectId ? (
                    <button
                      type="button"
                      onClick={() => onOpenTab("workflow")}
                      className="rounded-full border border-sky-500/20 bg-sky-950/20 px-2.5 py-1 text-sky-200 transition hover:border-sky-400/30 hover:bg-sky-950/30"
                    >
                      Next thread target · {nextThreadProjectId}
                    </button>
                  ) : null}
                  {typeof contextPct === "number" ? (
                    <span
                      className={cn(
                        "rounded-full border px-2.5 py-1",
                        contextPct >= 80
                          ? "border-amber-500/20 bg-amber-950/20 text-amber-200"
                          : "border-slate-700 bg-slate-900/80",
                      )}
                    >
                      Runtime context · {Math.round(contextPct)}%
                    </span>
                  ) : null}
                  {!compactViewport && terminalPersonaThread ? (
                    <span className="rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1 text-slate-300">
                      Replies continue in this persisted thread until you start fresh.
                    </span>
                  ) : null}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 xl:justify-end">
                <button
                  type="button"
                  onClick={() => sendMessage("Pause and give concise status: current goal, blocker, active lane, and next move.")}
                  className={cn(
                    "inline-flex items-center gap-2 border border-slate-700 bg-slate-900/80 font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800",
                    compactViewport ? "rounded-lg px-2.5 py-1 text-xs" : "rounded-xl px-3 py-1.5 text-sm",
                  )}
                >
                  Ask status
                </button>
                <button
                  type="button"
                  onClick={onToggleDesk}
                  className={cn(
                    "inline-flex items-center gap-2 border border-slate-700 bg-slate-900/80 font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800 lg:hidden",
                    compactViewport ? "rounded-lg px-2.5 py-1 text-xs" : "rounded-xl px-3 py-1.5 text-sm",
                  )}
                >
                  <PanelsRightBottom className="h-4 w-4" />
                  {compactViewport ? "Desk" : deskOpen ? "Hide desk" : "Open desk"}
                </button>
                <div
                  className={cn(
                    "hidden items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-3 py-1.5 text-sm font-medium text-slate-200 lg:inline-flex",
                    compactViewport && "text-xs",
                  )}
                >
                  <PanelsRightBottom className="h-4 w-4" />
                  Desk pinned
                </div>
              </div>
            </div>

            {runtime.activeChildSessions.length > 0 || !mainThreadSelected ? (
              <div className={cn("mt-3 flex items-center gap-2 overflow-x-auto", compactViewport ? "pb-0.5" : "pb-1")}>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => onSelectSession(null)}
                    className={cn(
                      "inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition",
                      mainThreadSelected
                        ? "border-emerald-500/30 bg-emerald-950/30 text-emerald-200"
                        : "border-slate-700 bg-slate-950/70 text-slate-300 hover:border-slate-600 hover:bg-slate-900",
                    )}
                  >
                    <Bot className="h-3.5 w-3.5" />
                    Main thread
                  </button>
                  {runtime.activeChildSessions.map((session) => (
                    <button
                      key={session.id}
                      type="button"
                      onClick={() => onSelectSession(session.id)}
                      className={cn(
                        "inline-flex max-w-full items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition",
                        selectedSessionId === session.id
                          ? "border-amber-500/30 bg-amber-950/30 text-amber-200"
                          : "border-slate-700 bg-slate-950/70 text-slate-300 hover:border-slate-600 hover:bg-slate-900",
                      )}
                    >
                      <span className="truncate">{session.agent_slug || "lane"}</span>
                      <ChevronRight className="h-3 w-3 opacity-60" />
                      <span className="truncate text-slate-400">{summarize(session)}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </CommandSurface>
      </div>
    </div>
  );
}
