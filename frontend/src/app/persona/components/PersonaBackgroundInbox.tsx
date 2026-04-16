"use client";

import { formatDistanceToNowStrict } from "date-fns";
import { ArrowRightCircle, PauseCircle, PlayCircle } from "lucide-react";

import type { PersonaStreamEntry } from "@/lib/api/persona-stream";
import type { SessionListItem } from "@/lib/api/sessions";
import { cn } from "@/lib/utils";

interface PersonaBackgroundInboxProps {
  entries: PersonaStreamEntry[];
  activeChildSessions: SessionListItem[];
  activeSessionId: string | null;
  stoppingSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onStopSession: (sessionId: string) => void;
  onRedirectSession: (sessionId: string, summary: string) => void;
  onPromoteSession: (sessionId: string, summary: string) => void;
  onHandoffSession: (sessionId: string, summary: string) => void;
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

function summarizeEntry(entry: PersonaStreamEntry) {
  return entry.display_summary || entry.summary_oneliner || entry.live_summary || "No summary recorded";
}

function summarizeSession(session: SessionListItem) {
  return session.live_activity?.summary || "No summary recorded";
}

function chooseTimestamp(left: string, right: string) {
  return +new Date(left) >= +new Date(right) ? left : right;
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
  const lanes = Array.from(
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
    .slice(0, 6);

  const activeCount = lanes.filter((entry) => entry.status === "active" || entry.liveStatus === "active").length;

  return (
    <section
      data-testid="persona-background-inbox"
      className="rounded-[28px] border border-slate-800/70 bg-slate-900/80 p-4"
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            Background lanes
          </div>
          <h3 className="mt-2 text-lg font-semibold text-slate-50">
            Resume, inspect, and redirect side work without losing the main thread.
          </h3>
        </div>
        <div className="rounded-full border border-slate-700 bg-slate-950/70 px-2.5 py-1 text-xs text-slate-300">
          {activeCount}/{lanes.length} active
        </div>
      </div>

      <div className="mt-4 space-y-2">
        {lanes.length === 0 ? (
          <div className="rounded-2xl border border-slate-800/70 bg-slate-950/70 px-3 py-3 text-sm text-slate-400">
            No child lanes yet.
          </div>
        ) : null}
        {lanes.map((entry) => {
          const isActive = entry.status === "active" || entry.liveStatus === "active";
          return (
            <div
              key={entry.sessionId}
              className={cn(
                "rounded-2xl border px-3 py-3",
                activeSessionId === entry.sessionId
                  ? "border-sky-500/30 bg-sky-950/20"
                  : "border-slate-800/70 bg-slate-950/70",
              )}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-slate-100">{entry.agentSlug || "agent"}</span>
                    <span className="rounded-full border border-slate-700 bg-slate-900/70 px-2 py-0.5 text-[11px] text-slate-300">
                      {entry.projectId}
                    </span>
                    <span className="rounded-full border border-slate-700 bg-slate-900/70 px-2 py-0.5 text-[11px] text-slate-300">
                      {isActive ? "active" : entry.status}
                    </span>
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
                    className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
                  >
                    <PlayCircle className="h-4 w-4" />
                    Resume
                  </button>
                  <button
                    type="button"
                    onClick={() => onRedirectSession(entry.sessionId, entry.summary)}
                    className="inline-flex items-center gap-2 rounded-xl border border-amber-500/20 bg-amber-950/20 px-3 py-2 text-sm font-medium text-amber-200 transition hover:border-amber-400/30 hover:bg-amber-950/30"
                  >
                    <ArrowRightCircle className="h-4 w-4" />
                    Redirect
                  </button>
                  <button
                    type="button"
                    onClick={() => onPromoteSession(entry.sessionId, entry.summary)}
                    className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
                  >
                    Promote
                  </button>
                  <button
                    type="button"
                    onClick={() => onHandoffSession(entry.sessionId, entry.summary)}
                    className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-3 py-2 text-sm font-medium text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
                  >
                    Handoff
                  </button>
                  {isActive ? (
                    <button
                      type="button"
                      onClick={() => onStopSession(entry.sessionId)}
                      disabled={stoppingSessionId === entry.sessionId}
                      className="inline-flex items-center gap-2 rounded-xl border border-rose-500/20 bg-rose-950/20 px-3 py-2 text-sm font-medium text-rose-200 transition hover:border-rose-400/30 hover:bg-rose-950/30 disabled:opacity-60"
                    >
                      <PauseCircle className="h-4 w-4" />
                      {stoppingSessionId === entry.sessionId ? "Stopping" : "Stop"}
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
