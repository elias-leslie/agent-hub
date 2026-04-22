"use client";

import { useMemo, useState } from "react";
import { formatDistanceToNowStrict } from "date-fns";
import { PauseCircle, PlayCircle, SendHorizontal, X } from "lucide-react";

import type { PersonaStreamEntry } from "@/lib/api/persona-stream";
import type { SessionListItem } from "@/lib/api/sessions";
import { cn } from "@/lib/utils";
import { EvidencePanel, SectionEyebrow } from "./persona-operator-chrome";

interface PersonaBackgroundInboxProps {
  entries: PersonaStreamEntry[];
  activeChildSessions: SessionListItem[];
  activeSessionId: string | null;
  stoppingSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onStopSession: (sessionId: string) => void;
  onRedirectSession: (sessionId: string, draft: string) => void;
  onPromoteSession: (sessionId: string, draft: string) => void;
  onHandoffSession: (sessionId: string, draft: string) => void;
}

interface InboxLane {
  sessionId: string;
  projectId: string;
  agentSlug: string | null;
  status: string;
  liveStatus: string | null;
  summary: string;
  timestamp: string;
}

type LaneAction = "redirect" | "promote" | "handoff";

interface DraftState {
  laneId: string;
  action: LaneAction;
  text: string;
}

function summarizeEntry(entry: PersonaStreamEntry) {
  return entry.display_summary || entry.summary_oneliner || entry.live_summary || "No summary recorded";
}

function summarizeSession(session: SessionListItem) {
  return session.live_activity?.summary || "No summary recorded";
}

function chooseTimestamp(left: string, right: string) {
  return +new Date(left) >= +new Date(right) ? left : right;
}

function buildDraft(action: LaneAction, summary: string) {
  if (action === "redirect") {
    return `Adjust current work. ${summary}`;
  }
  if (action === "promote") {
    return `Summarize what should move back to the main thread. ${summary}`;
  }
  return `Summarize owner, blocker, and next move. ${summary}`;
}

export function PersonaBackgroundInbox({
  entries,
  activeChildSessions,
  activeSessionId,
  stoppingSessionId,
  onSelectSession,
  onStopSession,
  onRedirectSession,
  onPromoteSession,
  onHandoffSession,
}: PersonaBackgroundInboxProps) {
  const [draftState, setDraftState] = useState<DraftState | null>(null);

  const lanes = useMemo(() => Array.from(
    entries
      .filter((entry) => entry.entry_type === "child_run")
      .reduce((map, entry) => {
        const existing = map.get(entry.session_id);
        const entrySummary = summarizeEntry(entry);
        map.set(entry.session_id, {
          sessionId: entry.session_id,
          projectId: existing?.projectId ?? entry.project_id,
          agentSlug: existing?.agentSlug ?? entry.agent_slug,
          status: existing?.status ?? entry.status,
          liveStatus: existing?.liveStatus ?? entry.live_status,
          summary:
            existing?.summary && existing.summary !== "No summary recorded"
              ? existing.summary
              : entrySummary,
          timestamp: existing ? chooseTimestamp(existing.timestamp, entry.timestamp) : entry.timestamp,
        });
        return map;
      }, activeChildSessions.reduce((map, session) => {
        map.set(session.id, {
          sessionId: session.id,
          projectId: session.project_id,
          agentSlug: session.agent_slug,
          status: session.status,
          liveStatus: session.live_activity?.status ?? null,
          summary: summarizeSession(session),
          timestamp: session.updated_at,
        });
        return map;
      }, new Map<string, InboxLane>()))
      .values(),
  )
    .sort((left, right) => {
      const leftActive = left.status === "active" || left.liveStatus === "active" ? 1 : 0;
      const rightActive = right.status === "active" || right.liveStatus === "active" ? 1 : 0;
      if (leftActive !== rightActive) {
        return rightActive - leftActive;
      }
      return +new Date(right.timestamp) - +new Date(left.timestamp);
    })
    .slice(0, 6), [activeChildSessions, entries]);

  const activeCount = lanes.filter((entry) => entry.status === "active" || entry.liveStatus === "active").length;

  const submitDraft = () => {
    if (!draftState?.text.trim()) {
      return;
    }
    if (draftState.action === "redirect") {
      onRedirectSession(draftState.laneId, draftState.text.trim());
    } else if (draftState.action === "promote") {
      onPromoteSession(draftState.laneId, draftState.text.trim());
    } else {
      onHandoffSession(draftState.laneId, draftState.text.trim());
    }
    setDraftState(null);
  };

  return (
    <EvidencePanel data-testid="persona-background-inbox" className="p-4">
      <div className="flex items-center justify-between gap-3">
        <SectionEyebrow label={`Lanes · ${activeCount}/${lanes.length}`} source="runtime" />
      </div>

      <div className="mt-3 space-y-2">
        {lanes.length === 0 ? (
          <div className="text-sm text-slate-500">No child lanes.</div>
        ) : null}
        {lanes.map((entry) => {
          const isActive = entry.status === "active" || entry.liveStatus === "active";
          const isDraftOpen = draftState?.laneId === entry.sessionId;
          const statusLabel = isActive ? "active" : entry.status;
          return (
            <div
              key={entry.sessionId}
              className={cn(
                "rounded-lg border px-3 py-3",
                activeSessionId === entry.sessionId
                  ? "border-amber-500/30 bg-amber-950/10"
                  : "border-slate-800/70 bg-slate-950/70",
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span className={cn("h-2 w-2 rounded-full", isActive ? "bg-emerald-400" : "bg-slate-500")} />
                    <span className="font-medium text-slate-200">{entry.agentSlug || "agent"}</span>
                    <span>{statusLabel}</span>
                    <span>{entry.projectId}</span>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-slate-300">{entry.summary}</p>
                  <div className="mt-2 text-xs text-slate-500">
                    {formatDistanceToNowStrict(new Date(entry.timestamp), { addSuffix: true })}
                  </div>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => onSelectSession(entry.sessionId)}
                    className="inline-flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm font-medium text-slate-200 transition hover:border-slate-700 hover:bg-slate-900"
                  >
                    <PlayCircle className="h-4 w-4" />
                    Open
                  </button>
                  <button
                    type="button"
                    onClick={() => setDraftState({ laneId: entry.sessionId, action: "redirect", text: buildDraft("redirect", entry.summary) })}
                    className="inline-flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm font-medium text-slate-200 transition hover:border-slate-700 hover:bg-slate-900"
                  >
                    Draft
                  </button>
                  {isActive ? (
                    <button
                      type="button"
                      onClick={() => onStopSession(entry.sessionId)}
                      disabled={stoppingSessionId === entry.sessionId}
                      className="inline-flex items-center gap-2 rounded-lg border border-rose-500/20 bg-rose-950/15 px-3 py-2 text-sm font-medium text-rose-200 transition hover:border-rose-400/30 hover:bg-rose-950/25 disabled:opacity-60"
                    >
                      <PauseCircle className="h-4 w-4" />
                      {stoppingSessionId === entry.sessionId ? "Stopping" : "Stop"}
                    </button>
                  ) : null}
                </div>
              </div>
              {isDraftOpen ? (
                <div className="mt-3 rounded-lg border border-slate-800/70 bg-slate-950/70 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      value={draftState.action}
                      onChange={(event) => setDraftState((current) => current
                        ? { ...current, action: event.target.value as LaneAction, text: buildDraft(event.target.value as LaneAction, entry.summary) }
                        : current)}
                      className="rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none"
                    >
                      <option value="redirect">Redirect</option>
                      <option value="promote">Promote</option>
                      <option value="handoff">Handoff</option>
                    </select>
                    <span className="text-xs text-slate-500">Draft before send.</span>
                  </div>
                  <textarea
                    aria-label="Lane draft"
                    value={draftState.text}
                    onChange={(event) => setDraftState((current) => current ? { ...current, text: event.target.value } : current)}
                    rows={4}
                    className="mt-3 min-h-[120px] w-full rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none"
                  />
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={submitDraft}
                      disabled={!draftState.text.trim()}
                      className="inline-flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-950/20 px-3 py-2 text-sm font-medium text-amber-200 transition hover:border-amber-400/30 hover:bg-amber-950/30 disabled:opacity-60"
                    >
                      <SendHorizontal className="h-4 w-4" />
                      Send draft
                    </button>
                    <button
                      type="button"
                      onClick={() => setDraftState(null)}
                      className="inline-flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/80 px-3 py-2 text-sm font-medium text-slate-200 transition hover:border-slate-700 hover:bg-slate-900"
                    >
                      <X className="h-4 w-4" />
                      Cancel
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </EvidencePanel>
  );
}
