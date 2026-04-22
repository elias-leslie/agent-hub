"use client";

import { useMemo, useState } from "react";
import {
  Loader2,
  MessageSquarePlus,
  ChevronDown,
  Compass,
  SendHorizontal,
} from "lucide-react";
import { MessageInput } from "@agent-hub/chat-ui";
import { fetchApi, getApiBaseUrl, getWsUrl } from "@/lib/api-config";
import { cn } from "@/lib/utils";
import { ProvenanceBadge } from "./persona-operator-chrome";

interface WorkspaceChatFooterProps {
  personaDisplayName: string;
  responseStatusLabel: string | null;
  status: string;
  targetProjectId: string;
  sessionProjectId: string | null;
  threadSessionId?: string | null;
  threadSource?: "draft" | "session" | null;
  isTerminalThread?: boolean;
  sendMessage: (content: string, targetAgents?: string[], sessionIdOverride?: string) => void;
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
  threadSessionId = null,
  threadSource = null,
  isTerminalThread = false,
  sendMessage,
  cancelStream,
  preferencesEndpoint,
  onNewSession,
  compactViewport = false,
}: WorkspaceChatFooterProps) {
  const [redirectText, setRedirectText] = useState("");
  const [steerOpen, setSteerOpen] = useState(false);
  const threadMode = threadSource ?? (threadSessionId ? "session" : null);
  const sessionLocked = threadMode === "session" || threadMode === "draft";
  const lockedProjectId = sessionProjectId ?? targetProjectId;
  const projectLabel =
    threadMode === "session"
      ? `${isTerminalThread ? "Reply thread project" : "Persisted thread project"}: ${lockedProjectId}`
      : threadMode === "draft"
        ? `Draft thread target: ${lockedProjectId}`
        : `New thread target: ${targetProjectId}`;
  const nextThreadLabel =
    threadMode === "session" && lockedProjectId !== targetProjectId ? `Next thread target: ${targetProjectId}` : null;

  const draftCopy = useMemo(() => {
    if (threadMode === "session") {
      return {
        badge: "session" as const,
        helper: "Advisory redirect draft. Inspect before send. It adds new instruction to this persisted thread, does not rewrite prior messages, and does not silently fork a lane.",
        placeholder: "Redirect session: change direction, tighten scope, or request a checkpoint.",
        buttonLabel: "Send advisory redirect",
        messagePrefix: "Advisory redirect for the persisted thread:",
      };
    }
    if (threadMode === "draft") {
      return {
        badge: "draft" as const,
        helper: "Advisory draft update for the current draft thread. Inspect before send. It keeps draft provenance explicit until the thread is persisted.",
        placeholder: "Update draft thread: change direction, tighten scope, or request a checkpoint.",
        buttonLabel: "Send draft update",
        messagePrefix: "Advisory update for the current draft thread:",
      };
    }
    return {
      badge: "advisory" as const,
      helper: "Advisory steering draft for the next thread. Inspect before send. It shapes the next thread without pretending a persisted session already exists.",
      placeholder: "Steer next thread: set direction, scope, or the first checkpoint.",
      buttonLabel: "Send steering draft",
      messagePrefix: "Advisory steering for the next thread:",
    };
  }, [threadMode]);

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
              <ProvenanceBadge source="advisory" className="ml-1" />
              <ChevronDown className={`h-3.5 w-3.5 transition ${steerOpen ? "rotate-180" : ""}`} />
            </button>
            {threadMode ? <ProvenanceBadge source={threadMode} /> : null}
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
          </div>
          {steerOpen ? (
            <div className={cn(compactViewport ? "mt-1.5 space-y-2" : "mt-2 space-y-2")}>
              <div className="flex flex-wrap items-center gap-2">
                <ProvenanceBadge source={draftCopy.badge} />
                <ProvenanceBadge source="advisory" />
              </div>
              <p className="text-xs leading-5 text-slate-400">{draftCopy.helper}</p>
              <div className="flex gap-2">
                <input
                  value={redirectText}
                  onChange={(event) => setRedirectText(event.target.value)}
                  placeholder={draftCopy.placeholder}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-600"
                />
                <button
                  type="button"
                  onClick={() => {
                    if (!redirectText.trim()) return;
                    const content = `${draftCopy.messagePrefix} ${redirectText.trim()}`;
                    if (sessionLocked && threadSessionId) {
                      sendMessage(content, undefined, threadSessionId);
                    } else {
                      sendMessage(content);
                    }
                    setRedirectText("");
                  }}
                  disabled={!redirectText.trim()}
                  className="inline-flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-950/20 px-3 py-2 text-sm font-medium text-amber-200 transition hover:border-amber-400/30 hover:bg-amber-950/30 disabled:opacity-60"
                >
                  <SendHorizontal className="h-4 w-4" />
                  {draftCopy.buttonLabel}
                </button>
              </div>
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
                {threadMode === "draft"
                  ? "Current draft thread stays local until persisted. New thread starts fresh on target."
                  : isTerminalThread
                    ? "Reply continues in this persisted thread. New thread starts fresh on target."
                    : "Current persisted thread stays locked. New thread picks target."}
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
