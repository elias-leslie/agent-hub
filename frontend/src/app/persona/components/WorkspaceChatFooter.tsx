"use client";

import { useState } from "react";
import {
  Loader2,
  MessageSquarePlus,
  ArrowRightCircle,
  SplitSquareVertical,
  ClipboardList,
  ChevronDown,
  Compass,
} from "lucide-react";
import { MessageInput } from "@agent-hub/chat-ui";
import { fetchApi, getApiBaseUrl, getWsUrl } from "@/lib/api-config";
import { cn } from "@/lib/utils";

interface WorkspaceChatFooterProps {
  personaDisplayName: string;
  responseStatusLabel: string | null;
  status: string;
  targetProjectId: string;
  sessionProjectId: string | null;
  isTerminalThread?: boolean;
  sendMessage: (content: string) => void;
  cancelStream: () => void;
  preferencesEndpoint: string;
  onNewSession: () => void;
  compactViewport?: boolean;
}

export function WorkspaceChatFooter({
  personaDisplayName,
  responseStatusLabel,
  status,
  targetProjectId,
  sessionProjectId,
  isTerminalThread = false,
  sendMessage,
  cancelStream,
  preferencesEndpoint,
  onNewSession,
  compactViewport = false,
}: WorkspaceChatFooterProps) {
  const [redirectText, setRedirectText] = useState("");
  const [steerOpen, setSteerOpen] = useState(false);
  const redirectLabel = status === "idle" ? `Steer ${personaDisplayName}` : `Redirect ${personaDisplayName}`;
  const sessionLocked = Boolean(sessionProjectId);
  const projectLabel = sessionLocked
    ? `${isTerminalThread ? "Reply thread" : "Thread project"}: ${sessionProjectId}`
    : `New thread target: ${targetProjectId}`;
  const nextThreadLabel =
    sessionLocked && sessionProjectId !== targetProjectId ? `Next thread target: ${targetProjectId}` : null;

  return (
    <div
      data-testid="persona-chat-footer"
      className={cn(
        "border-t border-slate-800/50 bg-[#0d0e13]/95 backdrop-blur-lg",
        compactViewport
          ? "px-3 py-1.5 shadow-[0_-16px_40px_-22px_rgba(2,6,23,0.96)]"
          : "px-4 py-2",
      )}
    >
      <div className="mx-auto max-w-4xl">
        <div
          className={cn(
            "rounded-[20px] border border-slate-800/70 bg-slate-950/80",
            compactViewport ? "mb-1.5 px-2.5 py-1.5" : "mb-2 px-3 py-2",
          )}
        >
          <div className={cn("flex items-center gap-2 overflow-x-auto", compactViewport ? "whitespace-nowrap" : "flex-wrap")}>
            <button
              type="button"
              onClick={() => setSteerOpen((current) => !current)}
              className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/20 bg-amber-950/20 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-200 transition hover:border-amber-400/30 hover:bg-amber-950/30"
            >
              <Compass className="h-3.5 w-3.5" />
              Steer
              <ChevronDown className={`h-3.5 w-3.5 transition ${steerOpen ? "rotate-180" : ""}`} />
            </button>
            <span className="rounded-full border border-sky-500/20 bg-sky-950/20 px-2.5 py-1 text-[11px] font-medium text-sky-200">
              {projectLabel}
            </span>
            {!compactViewport && nextThreadLabel ? (
              <span className="rounded-full border border-slate-700 bg-slate-900/70 px-2.5 py-1 text-[11px] font-medium text-slate-300">
                {nextThreadLabel}
              </span>
            ) : null}
            <button
              type="button"
              onClick={onNewSession}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-700 bg-slate-900/70 px-2.5 py-1 text-[11px] font-medium text-slate-300 transition hover:border-slate-600 hover:bg-slate-800"
            >
              <MessageSquarePlus className="h-3 w-3" />
              New thread
            </button>
            <button
              type="button"
              onClick={() => sendMessage("Pause and reply with concise status: current goal, blocker, lane owner, next move.")}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1 text-[11px] font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
            >
              <ClipboardList className="h-3.5 w-3.5" />
              Status
            </button>
            <button
              type="button"
              onClick={() => sendMessage("Revise the current plan. Keep what still holds. Show only the delta and rationale.")}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1 text-[11px] font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
            >
              <ArrowRightCircle className="h-3.5 w-3.5" />
              Plan
            </button>
            <button
              type="button"
              onClick={() => sendMessage("Split off any safe background lane you need, then report owners and expected outputs.")}
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-700 bg-slate-900/80 px-2.5 py-1 text-[11px] font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
            >
              <SplitSquareVertical className="h-3.5 w-3.5" />
              Lane
            </button>
          </div>
          {steerOpen ? (
            <div className={cn("flex gap-2", compactViewport ? "mt-1.5" : "mt-2")}>
              <input
                value={redirectText}
                onChange={(event) => setRedirectText(event.target.value)}
                placeholder={`${redirectLabel}: change direction, tighten scope, or ask for a checkpoint.`}
                className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-600"
              />
              <button
                type="button"
                onClick={() => {
                  if (!redirectText.trim()) return;
                  sendMessage(`Redirect current work: ${redirectText.trim()}`);
                  setRedirectText("");
                }}
                disabled={!redirectText.trim()}
                className="rounded-xl border border-amber-500/20 bg-amber-950/20 px-3 py-2 text-sm font-medium text-amber-200 transition hover:border-amber-400/30 hover:bg-amber-950/30 disabled:opacity-60"
              >
                Redirect
              </button>
            </div>
          ) : null}
        </div>
        {(responseStatusLabel || (sessionLocked && !compactViewport)) ? (
          <div className={cn("flex items-center justify-between gap-3 text-[11px] text-slate-500", compactViewport ? "mb-1" : "mb-1.5")}>
            <div className="flex items-center gap-2">
              {responseStatusLabel ? (
                <span className="inline-flex items-center gap-1.5 text-amber-400/80">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  {responseStatusLabel}
                </span>
              ) : null}
            </div>
            {sessionLocked && !compactViewport ? (
              <span className="truncate text-slate-600">
                {isTerminalThread
                  ? "Reply continues this thread. New thread starts fresh on target."
                  : "Current thread stays locked. New thread picks target."}
              </span>
            ) : null}
          </div>
        ) : null}
        <MessageInput
          onSend={sendMessage}
          onCancel={cancelStream}
          status={status as Parameters<typeof MessageInput>[0]["status"]}
          compact
          voiceWsUrl={getWsUrl("/api/voice/ws?user_id=agent_hub_user&app=agent-hub&mode=transcribe")}
          ttsBaseUrl={getApiBaseUrl() || window.location.origin}
          preferencesEndpoint={preferencesEndpoint}
          fetchFn={fetchApi}
        />
      </div>
    </div>
  );
}
