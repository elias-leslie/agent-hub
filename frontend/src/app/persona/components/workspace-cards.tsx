"use client";

import { useMemo, useState } from "react";
import {
  AlertCircle,
  Bot,
  ChevronDown,
  ChevronRight,
  Clock3,
  HeartPulse,
  Loader2,
  Sparkles,
  Wrench,
} from "lucide-react";

import type { PersonaIssueMarker, PersonaPulseSummary, PersonaStreamEntry } from "@/lib/api/persona-stream";
import type { TimelineEvent } from "@/types/events";
import { cn } from "@/lib/utils";
import {
  filterIssueMarkers,
  type FilterMode,
  visibleIssueMarkers,
  pulseTagToFilterMode,
  pulseTagClasses,
  pulseTagLabel,
  rootCauseLabel,
} from "./pulse-helpers";
import type {
  FeedChildRun,
  FeedHeartbeat,
  RoutineHeartbeatTimelineBlock,
  SessionEventDetailsState,
} from "./workspace-types";
import {
  entryStatusClasses,
  ExpandableText,
  formatRuntimeLabel,
  formatTimeLabel,
  isGenericStatusText,
  isPromptLikeText,
  isRecord,
  prettifyDisplayText,
  rootCauseClasses,
  TimelineTimestamp,
} from "./workspace-utils";
import { describeValue } from "./workspace-event-details";
import type { NarrationTag } from "../hooks/useNarrationTags";

// ─── Strip observability tags from display text ───

// Match [[P:type:content]] and truncated variants like [[P:found… or [[P:started:text...
const NARRATION_TAG_RE = /\[\[P:[a-z_]+(?::[^\]]*?)?\]?\]?/g;
// Match "Applied: [M:8hexchars]" and bare "[M:hexchars]" citations
const APPLIED_CITATION_RE = /\s*(?:Applied:\s*)?\[(?:M|G|R):[a-f0-9]{3,8}[^\]]*\]?/g;
// Match [[F:...]] feedback tags
const FEEDBACK_RE = /\[\[F:[^\]]*\]?\]?/g;
// Match [[S:...]] summary tags
const SUMMARY_RE = /\[\[S:[^\]]*\]?\]?/g;

function cleanSummary(text: string | null | undefined): string {
  if (!text) return "";
  let cleaned = text
    .replace(NARRATION_TAG_RE, "")
    .replace(APPLIED_CITATION_RE, "")
    .replace(FEEDBACK_RE, "")
    .replace(SUMMARY_RE, "")
    // Strip internal heartbeat prefixes
    .replace(/^HEARTBEAT_(?:OK|ACTION)\s*[—–\-]?\s*/i, "");
  // Clean orphaned bracket fragments left after tag stripping
  cleaned = cleaned
    .replace(/\[…/g, "")
    .replace(/^\[+\s*$/g, "")
    .replace(/\[+\s*\.\.\./g, "")
    .replace(/\.\.\./g, "…")
    .replace(/\n{2,}/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
  // If only punctuation/brackets/braces remain, return empty
  if (/^[\[\]{}\(\)…\s.,;:]*$/.test(cleaned)) return "";
  return cleaned;
}

// ─── Helpers for extracting human-readable text from events ───

function extractToolCallSummary(toolInput: unknown): string {
  if (!isRecord(toolInput)) return "";
  const keys = ["command", "action", "description", "file_path", "path", "query", "prompt", "slug", "pattern"];
  for (const key of keys) {
    const val = describeValue(toolInput[key]);
    if (val && val.length < 120) return `${key}="${val}"`;
    if (val) return `${key}="${val.slice(0, 80)}…"`;
  }
  return "";
}

function extractToolResult(toolOutput: unknown): string {
  if (typeof toolOutput === "string") {
    return prettifyDisplayText(toolOutput) || "";
  }
  if (!isRecord(toolOutput)) return "";
  const keys = ["content", "summary", "stdout", "message", "error_message", "stderr"];
  for (const key of keys) {
    const val = toolOutput[key];
    if (typeof val === "string" && val.trim()) {
      return prettifyDisplayText(val) || "";
    }
  }
  // Fallback: try to find any string value
  for (const val of Object.values(toolOutput)) {
    if (typeof val === "string" && val.trim() && val.length < 300) {
      return prettifyDisplayText(val) || "";
    }
  }
  return "";
}

function isNoiseEvent(event: TimelineEvent): boolean {
  if (event.event_type === "memory_inject" || event.event_type === "memory_cite") return true;
  if (event.event_type === "system_message") return true;
  if (event.event_type === "user_message") return true;
  if (event.event_type === "thinking") {
    const text = (event.content || "").toLowerCase();
    return !text.includes("error") && !text.includes("blocked") && !text.includes("failed");
  }
  if (event.event_type === "assistant_message") {
    if (isPromptLikeText(event.content)) return true;
    if (isGenericStatusText(event.content)) return true;
    if (!event.content || event.content.trim().length === 0) return true;
    // Filter out messages that are only observability tags with no real content
    const cleaned = cleanSummary(event.content);
    if (!cleaned || cleaned.length === 0) return true;
  }
  return false;
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max) + "…";
}

// ─── SessionTranscript: chronological chat-like event stream ───

interface TranscriptItem {
  id: string;
  timestamp: string;
  kind: "message" | "tool_call" | "error" | "narration";
  // message fields
  content?: string;
  // tool_call fields
  toolName?: string;
  toolParam?: string;
  toolResult?: string;
  toolResultFull?: string;
  isError?: boolean;
  // narration fields
  tagType?: string;
  tagContent?: string;
  // issue
  issueTitle?: string;
}

function buildTranscriptItems(
  events: TimelineEvent[],
  narrationTags?: NarrationTag[],
): TranscriptItem[] {
  const items: TranscriptItem[] = [];
  const processedIds = new Set<string>();

  for (let i = 0; i < events.length; i++) {
    const event = events[i];
    if (processedIds.has(event.id)) continue;
    if (isNoiseEvent(event)) continue;

    // Pair tool_use + tool_result
    if (event.event_type === "tool_use") {
      processedIds.add(event.id);
      const param = extractToolCallSummary(event.tool_input);
      let result = "";
      let resultFull = "";
      let hasError = false;

      // Look for matching tool_result
      const next = events[i + 1];
      if (next?.event_type === "tool_result" && next.turn === event.turn && next.tool_name === event.tool_name) {
        processedIds.add(next.id);
        const raw = extractToolResult(next.tool_output);
        resultFull = raw;
        result = truncate(raw, 150);
        const outputRecord = isRecord(next.tool_output) ? next.tool_output : null;
        hasError = outputRecord?.is_error === true
          || outputRecord?.exit_code === 1
          || (outputRecord?.status as string)?.toLowerCase() === "failed"
          || raw.toLowerCase().startsWith("error");
        i++; // skip the paired result
      }

      items.push({
        id: event.id,
        timestamp: event.created_at,
        kind: "tool_call",
        toolName: event.tool_name || "tool",
        toolParam: param,
        toolResult: result,
        toolResultFull: resultFull.length > result.length ? resultFull : undefined,
        isError: hasError,
      });
      continue;
    }

    // Standalone tool_result (no pair)
    if (event.event_type === "tool_result") {
      processedIds.add(event.id);
      const raw = extractToolResult(event.tool_output);
      items.push({
        id: event.id,
        timestamp: event.created_at,
        kind: "tool_call",
        toolName: event.tool_name || "tool",
        toolResult: truncate(raw, 150),
        toolResultFull: raw.length > 150 ? raw : undefined,
      });
      continue;
    }

    // Error events
    if (event.event_type === "error") {
      processedIds.add(event.id);
      items.push({
        id: event.id,
        timestamp: event.created_at,
        kind: "error",
        content: prettifyDisplayText(event.content || "Unknown error") || "Unknown error",
      });
      continue;
    }

    // Assistant messages (Jenny speaking)
    if (event.event_type === "assistant_message" && event.content) {
      processedIds.add(event.id);
      items.push({
        id: event.id,
        timestamp: event.created_at,
        kind: "message",
        content: cleanSummary(prettifyDisplayText(event.content || "")),
      });
      continue;
    }

    // Thinking with error content
    if (event.event_type === "thinking" && event.content) {
      processedIds.add(event.id);
      items.push({
        id: event.id,
        timestamp: event.created_at,
        kind: "message",
        content: cleanSummary(prettifyDisplayText(event.content || "")),
      });
      continue;
    }
  }

  // Interleave narration tags by timestamp
  if (narrationTags && narrationTags.length > 0) {
    for (const tag of narrationTags) {
      items.push({
        id: `narration-${tag.id}`,
        timestamp: tag.created_at,
        kind: "narration",
        tagType: tag.tag_type,
        tagContent: tag.content,
      });
    }
  }

  // Sort chronologically
  items.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

  return items;
}

const NARRATION_ICONS: Record<string, string> = {
  started: "▸",
  found: "🔍",
  modified: "✏️",
  tested: "✓",
  confidence: "📊",
  blocked: "⚠",
  decision: "⚖️",
};

function SessionTranscript({
  events,
  narrationTags,
  narrationLoading,
  issueMarkers,
  personaName,
}: {
  events: TimelineEvent[];
  narrationTags?: NarrationTag[];
  narrationLoading?: boolean;
  issueMarkers?: PersonaIssueMarker[];
  personaName?: string;
}) {
  const items = useMemo(() => buildTranscriptItems(events, narrationTags), [events, narrationTags]);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (narrationLoading) {
    return (
      <div className="mt-3 flex items-center gap-2 border-t border-slate-800 pt-3 text-xs text-slate-500">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />Loading...
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="mt-3 rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-2 text-xs text-slate-500">
        No detailed activity recorded.
      </div>
    );
  }

  const name = personaName || "Jenny";

  return (
    <div className="mt-3 border-t border-slate-800 pt-3 space-y-1.5">
      {items.map((item) => {
        if (item.kind === "message") {
          return (
            <div key={item.id} className="text-xs leading-relaxed">
              <span className="font-medium text-slate-300">{name}:</span>{" "}
              <span className="text-slate-400">
                {item.content && item.content.length > 200 ? (
                  expandedIds.has(item.id) ? (
                    <>
                      <span className="whitespace-pre-wrap">{item.content}</span>
                      <button onClick={(e) => { e.stopPropagation(); toggleExpand(item.id); }} className="ml-1 text-slate-500 hover:text-slate-300">less</button>
                    </>
                  ) : (
                    <>
                      {truncate(item.content, 200)}
                      <button onClick={(e) => { e.stopPropagation(); toggleExpand(item.id); }} className="ml-1 text-slate-500 hover:text-slate-300">more</button>
                    </>
                  )
                ) : (
                  item.content
                )}
              </span>
            </div>
          );
        }

        if (item.kind === "tool_call") {
          const paramStr = item.toolParam ? `(${item.toolParam})` : "";
          const isExpanded = expandedIds.has(item.id);
          return (
            <div key={item.id} className="text-xs font-mono">
              <div className="text-slate-400">
                <span className="text-slate-500">•</span>{" "}
                Ran <span className="text-slate-300">{item.toolName}</span>
                {paramStr && <span className="text-slate-500">{paramStr}</span>}
              </div>
              {item.toolResult && (
                <div className={cn("ml-3 mt-0.5", item.isError ? "text-rose-400" : "text-slate-500")}>
                  <span className="text-slate-600">└</span>{" "}
                  {item.toolResultFull && !isExpanded ? (
                    <>
                      {item.toolResult}
                      <button
                        onClick={(e) => { e.stopPropagation(); toggleExpand(item.id); }}
                        className="ml-1 text-slate-600 hover:text-slate-400 font-sans"
                      >
                        more
                      </button>
                    </>
                  ) : item.toolResultFull && isExpanded ? (
                    <>
                      <span className="whitespace-pre-wrap break-words font-sans">{item.toolResultFull}</span>
                      <button
                        onClick={(e) => { e.stopPropagation(); toggleExpand(item.id); }}
                        className="ml-1 text-slate-600 hover:text-slate-400 font-sans"
                      >
                        less
                      </button>
                    </>
                  ) : (
                    item.toolResult
                  )}
                </div>
              )}
            </div>
          );
        }

        if (item.kind === "error") {
          return (
            <div key={item.id} className="text-xs text-rose-400">
              <span className="text-rose-500">⚠</span> {item.content}
            </div>
          );
        }

        if (item.kind === "narration") {
          const icon = NARRATION_ICONS[item.tagType || ""] || "▸";
          if (item.tagType === "confidence") {
            const match = (item.tagContent || "").match(/^(\d+)/);
            const pct = match ? parseInt(match[1], 10) : null;
            const rest = (item.tagContent || "").replace(/^\d+\s*[-–—:]\s*/, "");
            return (
              <div key={item.id} className="text-xs text-violet-400 flex items-center gap-1.5">
                <span>{icon}</span>
                {pct !== null && (
                  <>
                    <div className="h-1.5 w-12 rounded-full bg-slate-800 overflow-hidden">
                      <div
                        className={cn("h-full rounded-full", pct >= 70 ? "bg-emerald-400" : pct >= 40 ? "bg-amber-400" : "bg-rose-400")}
                        style={{ width: `${Math.min(pct, 100)}%` }}
                      />
                    </div>
                    <span>{pct}%</span>
                  </>
                )}
                {rest && <span className="text-slate-500">{rest}</span>}
              </div>
            );
          }
          return (
            <div key={item.id} className={cn(
              "text-xs",
              item.tagType === "blocked" ? "text-rose-400" : "text-slate-400",
            )}>
              <span className={item.tagType === "blocked" ? "text-rose-500" : "text-slate-500"}>{icon}</span>{" "}
              <span className="font-medium capitalize">{item.tagType}:</span> {item.tagContent}
            </div>
          );
        }

        return null;
      })}

      {/* Trailing issues not matched to events */}
      {issueMarkers && issueMarkers.length > 0 && (
        <div className="mt-2 space-y-1">
          {issueMarkers.map((marker) => (
            <div key={`issue-${marker.event_id}-${marker.primary_tag}`} className="text-xs text-amber-400">
              <span className="text-amber-500">⚠</span>{" "}
              <span className="font-medium">{pulseTagLabel(marker.primary_tag)}:</span>{" "}
              {marker.title}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── EntryIssueSummary (compact inline on collapsed card) ───

export function EntryIssueSummary({ issueMarkers }: { issueMarkers: PersonaIssueMarker[] }) {
  const primaryMarker = issueMarkers[0];
  if (!primaryMarker) return null;

  return (
    <div className="mt-1.5 flex items-center gap-1.5">
      <span className={cn("rounded-full px-1.5 py-0.5 text-[10px]", pulseTagClasses(primaryMarker.primary_tag))}>
        {pulseTagLabel(primaryMarker.primary_tag)}
      </span>
      <span className="text-[10px] text-slate-500 truncate">{primaryMarker.title}</span>
    </div>
  );
}

// ─── PulseOverviewPanels (collapsible) ───

export function PulseOverviewPanels({
  visiblePulseMetrics,
  pulse,
  applyPulseFilter,
  inspectAgentPulse,
}: {
  visiblePulseMetrics: PersonaPulseSummary["metrics"];
  pulse: PersonaPulseSummary;
  applyPulseFilter: (nextMode: FilterMode, nextAnchorEntryId?: string | null) => void;
  inspectAgentPulse: (agentSlugValue: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const totalFriction = pulse.metrics.reduce((sum, m) => sum + m.count, 0);

  if (visiblePulseMetrics.length === 0 && pulse.issue_groups.length === 0 && pulse.agent_scorecards.length === 0) return null;

  return (
    <div className="mb-4">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium text-slate-400 transition hover:bg-slate-800/50 hover:text-slate-300"
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <Sparkles className="h-3.5 w-3.5" />
        Health overview
        {totalFriction > 0 && (
          <span className="rounded-full bg-amber-950/40 px-2 py-0.5 text-[10px] text-amber-300">
            {totalFriction} events
          </span>
        )}
      </button>

      {expanded && (
        <div className="mt-2 space-y-3 rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          {visiblePulseMetrics.length > 0 && (
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
              {visiblePulseMetrics.map((metric) => {
                const mode = pulseTagToFilterMode(metric.key);
                return (
                  <button
                    key={metric.key} type="button" onClick={() => applyPulseFilter(mode)}
                    className={cn(
                      "rounded-lg border px-3 py-2 text-left transition",
                      metric.count > 0
                        ? "border-slate-700 bg-slate-800/50 hover:border-slate-600"
                        : "border-slate-800 bg-slate-900/60",
                    )}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", pulseTagClasses(metric.key))}>{metric.label}</span>
                      <span className="text-base font-semibold text-slate-100">{metric.count}</span>
                    </div>
                    <p className="mt-1 text-xs text-slate-400">{metric.description}</p>
                  </button>
                );
              })}
            </div>
          )}

          {(pulse.issue_groups.length > 0 || pulse.agent_scorecards.length > 0) && (
            <div className="grid gap-3 xl:grid-cols-[1.3fr_1fr]">
              <section>
                <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500 mb-2">
                  <AlertCircle className="h-3 w-3" />Repeated Friction
                </div>
                {pulse.issue_groups.length === 0 ? (
                  <p className="text-xs text-slate-500">No repeated issues.</p>
                ) : (
                  <div className="space-y-2">
                    {pulse.issue_groups.map((issue) => (
                      <button key={issue.fingerprint} type="button"
                        onClick={() => applyPulseFilter(pulseTagToFilterMode(issue.primary_tag), issue.latest_entry_id)}
                        className="w-full rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2 text-left transition hover:border-slate-700"
                      >
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", pulseTagClasses(issue.primary_tag))}>{pulseTagLabel(issue.primary_tag)}</span>
                          <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400">{issue.count}x</span>
                          {issue.root_cause && <span className={cn("rounded-full px-2 py-0.5 text-[10px]", rootCauseClasses(issue.root_cause))}>{rootCauseLabel(issue.root_cause)}</span>}
                        </div>
                        <div className="mt-1 text-xs font-medium text-slate-200">{issue.title}</div>
                      </button>
                    ))}
                  </div>
                )}
              </section>
              <section>
                <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500 mb-2">
                  <Sparkles className="h-3 w-3" />Agent Scorecards
                </div>
                {pulse.agent_scorecards.length === 0 ? (
                  <p className="text-xs text-slate-500">No agent sessions yet.</p>
                ) : (
                  <div className="space-y-2">
                    {pulse.agent_scorecards.map((sc) => {
                      const successRate = sc.session_count > 0 ? Math.round((sc.success_count / sc.session_count) * 100) : 0;
                      const runtimeLbl = formatRuntimeLabel(sc.median_runtime_seconds);
                      return (
                        <button key={sc.agent_slug} type="button" onClick={() => inspectAgentPulse(sc.agent_slug)}
                          className="w-full rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2 text-left transition hover:border-slate-700"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-medium text-slate-200">{sc.label}</span>
                            <span className="text-[10px] text-slate-500">{successRate}% / {sc.session_count} runs</span>
                          </div>
                          {(sc.friction_count > 0 || sc.error_count > 0 || runtimeLbl) && (
                            <div className="mt-1 flex flex-wrap gap-1.5 text-[10px] text-slate-500">
                              {sc.friction_count > 0 && <span className={cn("rounded-full px-1.5 py-0.5", pulseTagClasses("friction"))}>{sc.friction_count} friction</span>}
                              {sc.error_count > 0 && <span className="rounded-full bg-rose-950/40 px-1.5 py-0.5 text-rose-300">{sc.error_count} errors</span>}
                              {runtimeLbl && <span className="rounded-full bg-slate-800 px-1.5 py-0.5 text-slate-400">{runtimeLbl}</span>}
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>
                )}
              </section>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── RoutineHeartbeatGroup ───

export function RoutineHeartbeatGroup({
  block, expanded, onToggle, activeSessionId, activeIssueTag,
  expandedEntryIds, onToggleEntry, sessionEventDetails,
  narrationCache, onFetchNarration, personaName,
}: {
  block: RoutineHeartbeatTimelineBlock; expanded: boolean; onToggle: () => void;
  activeSessionId: string | null; activeIssueTag: string | null;
  expandedEntryIds: Record<string, boolean>;
  onToggleEntry: (entryId: string, sessionId: string) => void;
  sessionEventDetails: Record<string, SessionEventDetailsState>;
  narrationCache?: Record<string, { tags: NarrationTag[]; loading: boolean; error: string | null }>;
  onFetchNarration?: (taskId: string) => void;
  personaName?: string;
}) {
  const first = block.items[0]?.anchorItem;
  const last = block.items.at(-1)?.anchorItem;
  const timeRange = first && last ? `${formatTimeLabel(first.timestamp)} \u2013 ${formatTimeLabel(last.timestamp)}` : null;

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/40 px-3 py-2">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3"
      >
        <div className="flex items-center gap-2">
          <Clock3 className="h-3.5 w-3.5 text-slate-500" />
          <span className="text-xs font-medium text-slate-400">
            {block.items.length} routine heartbeats
          </span>
          {timeRange && <span className="text-[10px] text-slate-600">{timeRange}</span>}
        </div>
        {expanded ? <ChevronDown className="h-3.5 w-3.5 text-slate-500" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-500" />}
      </button>
      {expanded && (
        <div className="mt-2 space-y-2 border-t border-slate-800/60 pt-2">
          {block.items.map(({ anchorItem }) => (
            <div key={anchorItem.id} data-session-anchor={anchorItem.sessionId} data-testid="stream-item" data-stream-item-id={anchorItem.id} data-timestamp={anchorItem.timestamp.toISOString()} className="flex items-start gap-3">
              <TimelineTimestamp timestamp={anchorItem.timestamp} />
              <div className="min-w-0 flex-1">
                <HeartbeatCard
                  entry={anchorItem.entry} activeIssueTag={activeIssueTag} selected={anchorItem.sessionId === activeSessionId}
                  expanded={!!expandedEntryIds[anchorItem.id]} onToggle={() => onToggleEntry(anchorItem.id, anchorItem.sessionId)}
                  details={sessionEventDetails[anchorItem.sessionId]}
                  narrationTags={anchorItem.entry.external_id ? narrationCache?.[anchorItem.entry.external_id]?.tags : undefined}
                  narrationLoading={anchorItem.entry.external_id ? narrationCache?.[anchorItem.entry.external_id]?.loading : undefined}
                  personaName={personaName}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── ChildRunStack ───

export function ChildRunStack({
  childRuns, activeSessionId, activeIssueTag, expandedEntryIds,
  onToggle, matchedIds, activeMatchId, sessionEventDetails,
  narrationCache, onFetchNarration, personaName,
}: {
  childRuns: FeedChildRun[]; activeSessionId: string | null; activeIssueTag: string | null;
  expandedEntryIds: Record<string, boolean>;
  onToggle: (entryId: string, sessionId: string) => void;
  matchedIds: Set<string>; activeMatchId: string | null;
  sessionEventDetails: Record<string, SessionEventDetailsState>;
  narrationCache?: Record<string, { tags: NarrationTag[]; loading: boolean; error: string | null }>;
  onFetchNarration?: (taskId: string) => void;
  personaName?: string;
}) {
  return (
    <div className="ml-4 mt-2 border-l-2 border-sky-900/40 pl-3">
      <div className="space-y-2">
        {childRuns.map((childRun) => (
          <div key={childRun.id} data-session-anchor={childRun.sessionId} data-testid="stream-item" data-stream-item-id={childRun.id} data-timestamp={childRun.timestamp.toISOString()}
            className={cn("flex items-start gap-2 rounded-lg",
              matchedIds.has(childRun.id) && "px-2 py-1 ring-1 ring-amber-800",
              activeMatchId === childRun.id && "ring-2 ring-amber-500",
            )}
          >
            <div className="min-w-0 flex-1">
              <ChildRunCard
                entry={childRun.entry} activeIssueTag={activeIssueTag} selected={childRun.sessionId === activeSessionId}
                expanded={!!expandedEntryIds[childRun.id]} onToggle={() => onToggle(childRun.id, childRun.sessionId)}
                details={sessionEventDetails[childRun.sessionId]}
                narrationTags={childRun.entry.external_id ? narrationCache?.[childRun.entry.external_id]?.tags : undefined}
                narrationLoading={childRun.entry.external_id ? narrationCache?.[childRun.entry.external_id]?.loading : undefined}
                personaName={personaName}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── ChildRunCard (compact) ───

export function ChildRunCard({
  entry, activeIssueTag, selected, expanded, onToggle, details,
  narrationTags, narrationLoading, personaName,
}: {
  entry: PersonaStreamEntry; activeIssueTag: string | null; selected: boolean; expanded: boolean;
  onToggle: () => void; details?: SessionEventDetailsState;
  narrationTags?: NarrationTag[];
  narrationLoading?: boolean;
  personaName?: string;
}) {
  const issueMarkers = visibleIssueMarkers(entry, activeIssueTag);
  const primaryIssue = issueMarkers[0];
  const isActive = entry.status === "active";

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    onToggle();
  };

  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2 transition-colors cursor-pointer",
        selected ? "border-sky-800 bg-sky-950/20" : "border-slate-800/60 bg-slate-900/30 hover:border-slate-700",
      )}
      onClick={handleClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); onToggle(); } }}
    >
      <div className="flex items-center gap-2">
        <Bot className="h-3.5 w-3.5 text-sky-400 flex-shrink-0" />
        <span className="text-xs font-medium text-slate-200 truncate">{entry.agent_slug || "Agent"}</span>
        <span className="text-[10px] text-slate-600">on {entry.project_id}</span>
        {entry.external_id && <span className="rounded bg-amber-950/40 px-1.5 py-0.5 text-[10px] text-amber-300">{entry.external_id}</span>}
        <div className="flex-1" />
        <span className={cn("rounded-full px-1.5 py-0.5 text-[10px]", entryStatusClasses(entry.status))}>{entry.status}</span>
        {isActive && <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />}
        {entry.tool_count > 0 && <span className="inline-flex items-center gap-0.5 text-[10px] text-slate-500"><Wrench className="h-3 w-3" />{entry.tool_count}</span>}
        {expanded ? <ChevronDown className="h-3.5 w-3.5 text-slate-500" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-500" />}
      </div>

      <p className="mt-1 text-xs text-slate-400 leading-relaxed line-clamp-2">
        {cleanSummary(entry.summary_oneliner) || cleanSummary(entry.live_summary) || `Running on ${entry.project_id}`}
      </p>

      {primaryIssue && !expanded && <EntryIssueSummary issueMarkers={issueMarkers} />}

      {expanded && details && !details.loading && !details.error && (
        <SessionTranscript
          events={details.events}
          narrationTags={narrationTags}
          narrationLoading={narrationLoading}
          issueMarkers={issueMarkers}
          personaName={entry.agent_slug || personaName}
        />
      )}
      {expanded && details?.loading && (
        <div className="mt-3 flex items-center gap-2 border-t border-slate-800 pt-3 text-xs text-slate-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />Loading...
        </div>
      )}
      {expanded && details?.error && (
        <div className="mt-3 rounded-lg border border-rose-900/50 bg-rose-950/20 px-3 py-2 text-xs text-rose-400">{details.error}</div>
      )}
    </div>
  );
}

// ─── HeartbeatCard (compact) ───

export function HeartbeatCard({
  entry, activeIssueTag, selected, expanded, onToggle, details,
  narrationTags, narrationLoading, personaName,
}: {
  entry: PersonaStreamEntry; activeIssueTag: string | null; selected: boolean; expanded: boolean;
  onToggle: () => void; details?: SessionEventDetailsState;
  narrationTags?: NarrationTag[];
  narrationLoading?: boolean;
  personaName?: string;
}) {
  const issueMarkers = visibleIssueMarkers(entry, activeIssueTag);
  const primaryIssue = issueMarkers[0];
  const isActive = entry.status === "active";

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    onToggle();
  };

  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2 transition-colors cursor-pointer",
        selected ? "border-amber-800 bg-amber-950/15" : "border-slate-800/60 bg-slate-900/30 hover:border-slate-700",
      )}
      onClick={handleClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); onToggle(); } }}
    >
      <div className="flex items-center gap-2">
        <HeartPulse className={cn("h-3.5 w-3.5 flex-shrink-0", isActive ? "text-amber-400 animate-pulse" : "text-amber-500/70")} />
        <span className="text-xs font-medium text-slate-200">Heartbeat</span>
        {entry.external_id && <span className="rounded bg-amber-950/40 px-1.5 py-0.5 text-[10px] text-amber-300">{entry.external_id}</span>}
        <div className="flex-1" />
        <span className={cn("rounded-full px-1.5 py-0.5 text-[10px]", entryStatusClasses(entry.status))}>{entry.status}</span>
        {isActive && <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />}
        {entry.tool_count > 0 && <span className="inline-flex items-center gap-0.5 text-[10px] text-slate-500"><Wrench className="h-3 w-3" />{entry.tool_count}</span>}
        {expanded ? <ChevronDown className="h-3.5 w-3.5 text-slate-500" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-500" />}
      </div>

      <p className="mt-1 text-xs text-slate-400 leading-relaxed line-clamp-2">
        {cleanSummary(entry.summary_oneliner) || cleanSummary(entry.live_summary) || "Routine check completed"}
      </p>

      {primaryIssue && !expanded && <EntryIssueSummary issueMarkers={issueMarkers} />}

      {expanded && details && !details.loading && !details.error && (
        <SessionTranscript
          events={details.events}
          narrationTags={narrationTags}
          narrationLoading={narrationLoading}
          issueMarkers={issueMarkers}
          personaName={personaName}
        />
      )}
      {expanded && details?.loading && (
        <div className="mt-3 flex items-center gap-2 border-t border-slate-800 pt-3 text-xs text-slate-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />Loading...
        </div>
      )}
      {expanded && details?.error && (
        <div className="mt-3 rounded-lg border border-rose-900/50 bg-rose-950/20 px-3 py-2 text-xs text-rose-400">{details.error}</div>
      )}
    </div>
  );
}
