"use client";

import { useEffect, useMemo, useState } from "react";
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
  SessionDetailBlock,
  SessionEventDetailsState,
} from "./workspace-types";
import {
  badgeToneClasses,
  entryStatusClasses,
  eventAccentClasses,
  eventSummaryLabel,
  eventToneClasses,
  ExpandableText,
  formatRuntimeLabel,
  formatTimeLabel,
  rootCauseClasses,
  TimelineTimestamp,
} from "./workspace-utils";
import { buildIssueDetailBlocks, buildSessionDetailBlocks } from "./workspace-event-details";
import { NarrationTimeline } from "./NarrationTimeline";
import type { NarrationTag } from "../hooks/useNarrationTags";

// --- EntryIssueSummary (compact inline) ---

export function EntryIssueSummary({ issueMarkers }: { issueMarkers: PersonaIssueMarker[] }) {
  const primaryMarker = issueMarkers[0];
  if (!primaryMarker) return null;
  const additionalCount = Math.max(issueMarkers.length - 1, 0);

  return (
    <div className="mt-2 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", pulseTagClasses(primaryMarker.primary_tag))}>
          {pulseTagLabel(primaryMarker.primary_tag)}
        </span>
        {primaryMarker.primary_root_cause && (
          <span className={cn("rounded-full px-2 py-0.5 text-[10px]", rootCauseClasses(primaryMarker.primary_root_cause))}>
            {rootCauseLabel(primaryMarker.primary_root_cause)}
          </span>
        )}
        {additionalCount > 0 && (
          <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400">
            +{additionalCount} more
          </span>
        )}
      </div>
      <div className="mt-1 text-sm font-medium text-slate-200">{primaryMarker.title}</div>
      <ExpandableText
        text={primaryMarker.summary}
        expandedText={primaryMarker.detail}
        className="mt-1 block whitespace-pre-wrap break-words text-xs text-slate-400"
        collapsedLength={160}
      />
    </div>
  );
}

// --- SessionDetailBlockCard ---

export function SessionDetailBlockCard({ block }: { block: SessionDetailBlock }) {
  const headerTime = formatTimeLabel(new Date(block.timestamp));
  return (
    <div className={cn("rounded-lg border px-3 py-2.5 text-sm", eventToneClasses(block.eventType))}>
      <div className="flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-[0.14em]">
        <span className={cn("rounded-full px-2 py-0.5", eventAccentClasses(block.eventType))}>
          {eventSummaryLabel(block.eventType)}
        </span>
        <time dateTime={block.timestamp} className="inline-flex items-center gap-1 normal-case tracking-normal opacity-80">
          <Clock3 className="h-3 w-3" />{headerTime}
        </time>
        {block.title && <span className="normal-case tracking-normal font-medium">{block.title}</span>}
      </div>
      {block.lead && (
        <div className="mt-2 rounded-lg border border-white/5 bg-slate-950/60 px-2.5 py-2">
          <ExpandableText text={block.lead} className="block whitespace-pre-wrap break-words text-sm font-medium" collapsedLength={240} />
        </div>
      )}
      {block.textBlocks.map((text, index) => (
        <ExpandableText key={`${block.id}-text-${index}`} text={text} className="mt-2 block whitespace-pre-wrap break-words text-sm" collapsedLength={240} />
      ))}
      {block.fields.length > 0 && (
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          {block.fields.map((field) => (
            <div key={`${block.id}-${field.label}-${field.value}`} className="rounded-lg border border-white/5 bg-slate-950/60 px-2.5 py-1.5">
              <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{field.label}</div>
              <div className={cn("mt-0.5 rounded px-1.5 py-0.5", field.tone ? badgeToneClasses(field.tone) : "bg-slate-800/70")}>
                <ExpandableText text={field.value} className="block whitespace-pre-wrap break-words text-xs" collapsedLength={220} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --- PulseOverviewPanels (now collapsible, not default-shown) ---

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
                        ? "border-slate-700 bg-slate-800/50 hover:border-slate-600 hover:bg-slate-800"
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
                          <div className="mt-1 flex flex-wrap gap-1.5 text-[10px] text-slate-500">
                            {sc.friction_count > 0 && <span className={cn("rounded-full px-1.5 py-0.5", pulseTagClasses("friction"))}>{sc.friction_count} friction</span>}
                            {sc.error_count > 0 && <span className="rounded-full bg-rose-950/40 px-1.5 py-0.5 text-rose-300">{sc.error_count} errors</span>}
                            {runtimeLbl && <span className="rounded-full bg-slate-800 px-1.5 py-0.5 text-slate-400">{runtimeLbl}</span>}
                          </div>
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

// --- SessionDetailsPanel (compact) ---

export function SessionDetailsPanel({
  details,
  previewCount,
  issueMarkers,
  activeIssueTag,
  narrationTags,
  narrationLoading,
  narrationError,
}: {
  details: SessionEventDetailsState | undefined;
  previewCount: number;
  issueMarkers: PersonaIssueMarker[];
  activeIssueTag: string | null;
  narrationTags?: NarrationTag[];
  narrationLoading?: boolean;
  narrationError?: string | null;
}) {
  const [showFullTrace, setShowFullTrace] = useState(false);
  const detailEvents = details?.events ?? [];
  const detailResetKey = useMemo(() => detailEvents.map((e) => e.id).join("|"), [detailEvents]);
  const blocks = useMemo(() => buildSessionDetailBlocks(detailEvents), [detailEvents]);
  const filteredIssueMarkers = useMemo(() => filterIssueMarkers(issueMarkers, activeIssueTag), [activeIssueTag, issueMarkers]);
  const issueBlocks = useMemo(() => buildIssueDetailBlocks(blocks, filteredIssueMarkers), [blocks, filteredIssueMarkers]);
  const importantBlocks = useMemo(
    () => blocks.filter((b) => b.defaultVisible && !issueBlocks.some((ib) => ib.id === b.id)),
    [blocks, issueBlocks],
  );
  const visibleImportantBlocks = useMemo(() => {
    if (importantBlocks.length > 0) return importantBlocks.slice(0, 6);
    const fallback = blocks.filter((b) => b.score > 0).slice(0, Math.min(blocks.length, 3));
    return fallback.length > 0 ? fallback : blocks.slice(0, 1);
  }, [blocks, importantBlocks]);

  useEffect(() => { setShowFullTrace(false); }, [detailResetKey]);

  if (!details || details.loading) {
    return (
      <div className="mt-3 flex items-center gap-2 border-t border-slate-800 pt-3 text-xs text-slate-500">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />Loading details...
      </div>
    );
  }
  if (details.error) {
    return <div className="mt-3 rounded-lg border border-rose-900/50 bg-rose-950/20 px-3 py-2 text-xs text-rose-400">{details.error}</div>;
  }
  if (details.events.length === 0 && (!narrationTags || narrationTags.length === 0)) {
    return <div className="mt-3 rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-2 text-xs text-slate-500">No additional detail recorded.</div>;
  }

  const visibleBlocks = showFullTrace ? blocks : visibleImportantBlocks;

  return (
    <div className="mt-3 space-y-3 border-t border-slate-800 pt-3">
      {/* Narration tags progress timeline */}
      {(narrationTags && narrationTags.length > 0 || narrationLoading) && (
        <NarrationTimeline
          tags={narrationTags ?? []}
          loading={narrationLoading ?? false}
          error={narrationError ?? null}
        />
      )}

      {/* Issue markers */}
      {filteredIssueMarkers.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Issues</div>
          {issueBlocks.length > 0 ? (
            issueBlocks.slice(0, 3).map((b) => <SessionDetailBlockCard key={`issue-${b.id}`} block={b} />)
          ) : (
            filteredIssueMarkers.slice(0, 3).map((marker) => (
              <div key={`issue-marker-${marker.event_id}-${marker.primary_tag}`} className="rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-medium", pulseTagClasses(marker.primary_tag))}>{pulseTagLabel(marker.primary_tag)}</span>
                  {marker.primary_root_cause && <span className={cn("rounded-full px-2 py-0.5 text-[10px]", rootCauseClasses(marker.primary_root_cause))}>{rootCauseLabel(marker.primary_root_cause)}</span>}
                </div>
                <div className="mt-1 text-xs font-medium text-slate-200">{marker.title}</div>
                <ExpandableText text={marker.summary} expandedText={marker.detail} className="mt-1 block whitespace-pre-wrap break-words text-xs text-slate-400" collapsedLength={180} />
              </div>
            ))
          )}
        </div>
      )}

      {/* Key events / full trace */}
      {details.events.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
              {showFullTrace ? "Full trace" : "Key events"}
            </div>
            {blocks.length > visibleImportantBlocks.length && (
              <button type="button" onClick={() => setShowFullTrace((c) => !c)}
                className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium text-slate-400 transition hover:bg-slate-800 hover:text-slate-300"
              >
                {showFullTrace ? "Show key events" : `Show all ${blocks.length} events`}
              </button>
            )}
          </div>
          <div className="space-y-1.5">
            {visibleBlocks.map((b) => <SessionDetailBlockCard key={b.id} block={b} />)}
          </div>
        </div>
      )}
    </div>
  );
}

// --- RoutineHeartbeatGroup ---

export function RoutineHeartbeatGroup({
  block, expanded, onToggle, activeSessionId, activeIssueTag,
  expandedEntryIds, onToggleEntry, sessionEventDetails,
  narrationCache, onFetchNarration,
}: {
  block: RoutineHeartbeatTimelineBlock; expanded: boolean; onToggle: () => void;
  activeSessionId: string | null; activeIssueTag: string | null;
  expandedEntryIds: Record<string, boolean>;
  onToggleEntry: (entryId: string, sessionId: string) => void;
  sessionEventDetails: Record<string, SessionEventDetailsState>;
  narrationCache?: Record<string, { tags: NarrationTag[]; loading: boolean; error: string | null }>;
  onFetchNarration?: (taskId: string) => void;
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
                  narrationError={anchorItem.entry.external_id ? narrationCache?.[anchorItem.entry.external_id]?.error : undefined}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --- ChildRunStack ---

export function ChildRunStack({
  childRuns, activeSessionId, activeIssueTag, expandedEntryIds,
  onToggle, matchedIds, activeMatchId, sessionEventDetails,
  narrationCache, onFetchNarration,
}: {
  childRuns: FeedChildRun[]; activeSessionId: string | null; activeIssueTag: string | null;
  expandedEntryIds: Record<string, boolean>;
  onToggle: (entryId: string, sessionId: string) => void;
  matchedIds: Set<string>; activeMatchId: string | null;
  sessionEventDetails: Record<string, SessionEventDetailsState>;
  narrationCache?: Record<string, { tags: NarrationTag[]; loading: boolean; error: string | null }>;
  onFetchNarration?: (taskId: string) => void;
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
                narrationError={childRun.entry.external_id ? narrationCache?.[childRun.entry.external_id]?.error : undefined}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- ChildRunCard (compact) ---

export function ChildRunCard({
  entry, activeIssueTag, selected, expanded, onToggle, details,
  narrationTags, narrationLoading, narrationError,
}: {
  entry: PersonaStreamEntry; activeIssueTag: string | null; selected: boolean; expanded: boolean;
  onToggle: () => void; details?: SessionEventDetailsState;
  narrationTags?: NarrationTag[];
  narrationLoading?: boolean;
  narrationError?: string | null;
}) {
  const issueMarkers = visibleIssueMarkers(entry, activeIssueTag);
  const primaryIssue = issueMarkers[0];
  const isActive = entry.status === "active";

  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2 transition-colors cursor-pointer",
        selected ? "border-sky-800 bg-sky-950/20" : "border-slate-800/60 bg-slate-900/30 hover:border-slate-700",
      )}
      onClick={onToggle}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}
    >
      {/* Compact header line */}
      <div className="flex items-center gap-2">
        <Bot className="h-3.5 w-3.5 text-sky-400 flex-shrink-0" />
        <span className="text-xs font-medium text-slate-200 truncate">
          {entry.agent_slug || "Agent"}
        </span>
        <span className="text-[10px] text-slate-600">on {entry.project_id}</span>
        {entry.external_id && (
          <span className="rounded bg-amber-950/40 px-1.5 py-0.5 text-[10px] text-amber-300">{entry.external_id}</span>
        )}
        <div className="flex-1" />
        <span className={cn("rounded-full px-1.5 py-0.5 text-[10px]", entryStatusClasses(entry.status))}>
          {entry.status}
        </span>
        {isActive && <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />}
        {entry.tool_count > 0 && (
          <span className="inline-flex items-center gap-0.5 text-[10px] text-slate-500">
            <Wrench className="h-3 w-3" />{entry.tool_count}
          </span>
        )}
        {expanded ? <ChevronDown className="h-3.5 w-3.5 text-slate-500" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-500" />}
      </div>

      {/* Summary line */}
      <p className="mt-1 text-xs text-slate-400 leading-relaxed line-clamp-2">
        {entry.summary_oneliner || entry.live_summary || "Agent activity"}
      </p>

      {/* Inline issue indicator */}
      {primaryIssue && !expanded && (
        <div className="mt-1.5 flex items-center gap-1.5">
          <span className={cn("rounded-full px-1.5 py-0.5 text-[10px]", pulseTagClasses(primaryIssue.primary_tag))}>
            {pulseTagLabel(primaryIssue.primary_tag)}
          </span>
          <span className="text-[10px] text-slate-500 truncate">{primaryIssue.title}</span>
        </div>
      )}

      {/* Expanded details */}
      {expanded && (
        <SessionDetailsPanel
          details={details}
          previewCount={entry.event_previews.length}
          issueMarkers={issueMarkers}
          activeIssueTag={activeIssueTag}
          narrationTags={narrationTags}
          narrationLoading={narrationLoading}
          narrationError={narrationError}
        />
      )}
    </div>
  );
}

// --- HeartbeatCard (compact) ---

export function HeartbeatCard({
  entry, activeIssueTag, selected, expanded, onToggle, details,
  narrationTags, narrationLoading, narrationError,
}: {
  entry: PersonaStreamEntry; activeIssueTag: string | null; selected: boolean; expanded: boolean;
  onToggle: () => void; details?: SessionEventDetailsState;
  narrationTags?: NarrationTag[];
  narrationLoading?: boolean;
  narrationError?: string | null;
}) {
  const issueMarkers = visibleIssueMarkers(entry, activeIssueTag);
  const primaryIssue = issueMarkers[0];
  const isActive = entry.status === "active";

  return (
    <div
      className={cn(
        "rounded-lg border px-3 py-2 transition-colors cursor-pointer",
        selected ? "border-amber-800 bg-amber-950/15" : "border-slate-800/60 bg-slate-900/30 hover:border-slate-700",
      )}
      onClick={onToggle}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}
    >
      {/* Compact header line */}
      <div className="flex items-center gap-2">
        <HeartPulse className={cn("h-3.5 w-3.5 flex-shrink-0", isActive ? "text-amber-400 animate-pulse" : "text-amber-500/70")} />
        <span className="text-xs font-medium text-slate-200">Heartbeat</span>
        {entry.external_id && (
          <span className="rounded bg-amber-950/40 px-1.5 py-0.5 text-[10px] text-amber-300">{entry.external_id}</span>
        )}
        <div className="flex-1" />
        <span className={cn("rounded-full px-1.5 py-0.5 text-[10px]", entryStatusClasses(entry.status))}>
          {entry.status}
        </span>
        {isActive && <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />}
        {entry.tool_count > 0 && (
          <span className="inline-flex items-center gap-0.5 text-[10px] text-slate-500">
            <Wrench className="h-3 w-3" />{entry.tool_count}
          </span>
        )}
        {expanded ? <ChevronDown className="h-3.5 w-3.5 text-slate-500" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-500" />}
      </div>

      {/* Summary line */}
      <p className="mt-1 text-xs text-slate-400 leading-relaxed line-clamp-2">
        {entry.summary_oneliner || entry.live_summary || "Routine check completed"}
      </p>

      {/* Inline issue indicator */}
      {primaryIssue && !expanded && (
        <div className="mt-1.5 flex items-center gap-1.5">
          <span className={cn("rounded-full px-1.5 py-0.5 text-[10px]", pulseTagClasses(primaryIssue.primary_tag))}>
            {pulseTagLabel(primaryIssue.primary_tag)}
          </span>
          <span className="text-[10px] text-slate-500 truncate">{primaryIssue.title}</span>
        </div>
      )}

      {/* Expanded details */}
      {expanded && (
        <SessionDetailsPanel
          details={details}
          previewCount={entry.event_previews.length}
          issueMarkers={issueMarkers}
          activeIssueTag={activeIssueTag}
          narrationTags={narrationTags}
          narrationLoading={narrationLoading}
          narrationError={narrationError}
        />
      )}
    </div>
  );
}
