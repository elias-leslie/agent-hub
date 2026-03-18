"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Bot,
  ChevronDown,
  ChevronUp,
  Clock3,
  HeartPulse,
  Loader2,
  Sparkles,
  Wrench,
} from "lucide-react";

import type { PersonaIssueMarker, PersonaPulseSummary, PersonaStreamEntry } from "@/lib/api/persona-stream";
import { cn } from "@/lib/utils";
import {
  entryHasPulseTag,
  filterIssueMarkers,
  filterModeToPulseTag,
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
  isGenericStatusText,
  outcomeToneClasses,
  rootCauseClasses,
  shouldRenderPulseSummary,
  TimelineTimestamp,
} from "./workspace-utils";
import { buildIssueDetailBlocks, buildSessionDetailBlocks } from "./workspace-event-details";

// --- EntryIssueSummary ---

export function EntryIssueSummary({ issueMarkers }: { issueMarkers: PersonaIssueMarker[] }) {
  const primaryMarker = issueMarkers[0];
  if (!primaryMarker) return null;
  const additionalCount = Math.max(issueMarkers.length - 1, 0);

  return (
    <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/90 px-3 py-2 dark:border-slate-800 dark:bg-slate-950/50">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", pulseTagClasses(primaryMarker.primary_tag))}>
          {pulseTagLabel(primaryMarker.primary_tag)}
        </span>
        {primaryMarker.primary_root_cause && (
          <span className={cn("rounded-full px-2 py-0.5 text-[11px]", rootCauseClasses(primaryMarker.primary_root_cause))}>
            {rootCauseLabel(primaryMarker.primary_root_cause)}
          </span>
        )}
        {additionalCount > 0 && (
          <span className="rounded-full bg-slate-200/80 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            +{additionalCount} more
          </span>
        )}
      </div>
      <div className="mt-2 text-sm font-semibold text-slate-900 dark:text-slate-100">{primaryMarker.title}</div>
      <ExpandableText
        text={primaryMarker.summary}
        expandedText={primaryMarker.detail}
        className="mt-1 block whitespace-pre-wrap break-words text-sm text-slate-600 dark:text-slate-300"
        collapsedLength={160}
      />
    </div>
  );
}

// --- SessionDetailBlockCard ---

export function SessionDetailBlockCard({ block }: { block: SessionDetailBlock }) {
  const headerTime = formatTimeLabel(new Date(block.timestamp));
  return (
    <div className={cn("rounded-xl border px-3 py-3 text-sm", eventToneClasses(block.eventType))}>
      <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.14em]">
        <span className={cn("rounded-full px-2 py-0.5", eventAccentClasses(block.eventType))}>
          {eventSummaryLabel(block.eventType)}
        </span>
        <time dateTime={block.timestamp} className="inline-flex items-center gap-1 normal-case tracking-normal opacity-80">
          <Clock3 className="h-3 w-3" />{headerTime}
        </time>
        {block.title && <span className="normal-case tracking-normal font-medium">{block.title}</span>}
      </div>
      {block.lead && (
        <div className="mt-2 rounded-xl border border-black/5 bg-white/70 px-2.5 py-2 dark:border-white/5 dark:bg-slate-950/60">
          <ExpandableText text={block.lead} className="block whitespace-pre-wrap break-words text-sm font-medium" collapsedLength={240} />
        </div>
      )}
      {block.textBlocks.map((text, index) => (
        <ExpandableText key={`${block.id}-text-${index}`} text={text} className="mt-2 block whitespace-pre-wrap break-words text-sm" collapsedLength={240} />
      ))}
      {block.fields.length > 0 && (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {block.fields.map((field) => (
            <div key={`${block.id}-${field.label}-${field.value}`} className="rounded-xl border border-black/5 bg-white/70 px-3 py-2 dark:border-white/5 dark:bg-slate-950/60">
              <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">{field.label}</div>
              <div className={cn("mt-1 rounded-lg px-2 py-1", field.tone ? badgeToneClasses(field.tone) : "bg-slate-100/80 dark:bg-slate-900/70")}>
                <ExpandableText text={field.value} className="block whitespace-pre-wrap break-words text-sm" collapsedLength={220} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --- PulseOverviewPanels ---

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
  if (visiblePulseMetrics.length === 0 && pulse.issue_groups.length === 0 && pulse.agent_scorecards.length === 0) return null;

  return (
    <div className="mb-5 space-y-4">
      {visiblePulseMetrics.length > 0 && (
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          {visiblePulseMetrics.map((metric) => {
            const mode = pulseTagToFilterMode(metric.key);
            return (
              <button
                key={metric.key} type="button" onClick={() => applyPulseFilter(mode)}
                className={cn(
                  "rounded-2xl border px-3 py-3 text-left transition",
                  metric.count > 0
                    ? "border-slate-200 bg-slate-50 hover:border-slate-300 hover:bg-white dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-700 dark:hover:bg-slate-950"
                    : "border-slate-200/70 bg-slate-50/60 dark:border-slate-800 dark:bg-slate-900/60",
                )}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", pulseTagClasses(metric.key))}>{metric.label}</span>
                  <span className="text-lg font-semibold text-slate-900 dark:text-slate-100">{metric.count}</span>
                </div>
                <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">{metric.description}</p>
              </button>
            );
          })}
        </div>
      )}

      {(pulse.issue_groups.length > 0 || pulse.agent_scorecards.length > 0) && (
        <div className="grid gap-4 xl:grid-cols-[1.3fr_1fr]">
          <section className="rounded-2xl border border-slate-200 bg-slate-50/90 px-4 py-4 dark:border-slate-800 dark:bg-slate-900/70">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">
              <AlertCircle className="h-3.5 w-3.5" />Repeated Friction
            </div>
            {pulse.issue_groups.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">No repeated issue fingerprints in this window.</p>
            ) : (
              <div className="mt-3 space-y-3">
                {pulse.issue_groups.map((issue) => (
                  <button key={issue.fingerprint} type="button"
                    onClick={() => applyPulseFilter(pulseTagToFilterMode(issue.primary_tag), issue.latest_entry_id)}
                    className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-left transition hover:border-slate-300 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-slate-700"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", pulseTagClasses(issue.primary_tag))}>{pulseTagLabel(issue.primary_tag)}</span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">{issue.count} hits</span>
                      {issue.root_cause && <span className={cn("rounded-full px-2 py-0.5 text-[11px]", rootCauseClasses(issue.root_cause))}>{rootCauseLabel(issue.root_cause)}</span>}
                    </div>
                    <div className="mt-2 text-sm font-semibold text-slate-900 dark:text-slate-100">{issue.title}</div>
                    <ExpandableText text={issue.summary} className="mt-1 block whitespace-pre-wrap break-words text-sm text-slate-600 dark:text-slate-300" collapsedLength={160} />
                    <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400 dark:text-slate-500">
                      {issue.agent_slugs.map((s) => <span key={`${issue.fingerprint}-${s}`} className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">{s}</span>)}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </section>
          <section className="rounded-2xl border border-slate-200 bg-slate-50/90 px-4 py-4 dark:border-slate-800 dark:bg-slate-900/70">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">
              <Sparkles className="h-3.5 w-3.5" />Agent Scorecards
            </div>
            {pulse.agent_scorecards.length === 0 ? (
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">No agent sessions in this window yet.</p>
            ) : (
              <div className="mt-3 space-y-3">
                {pulse.agent_scorecards.map((scorecard) => {
                  const successRate = scorecard.session_count > 0 ? Math.round((scorecard.success_count / scorecard.session_count) * 100) : 0;
                  const runtimeLabel = formatRuntimeLabel(scorecard.median_runtime_seconds);
                  return (
                    <button key={scorecard.agent_slug} type="button" onClick={() => inspectAgentPulse(scorecard.agent_slug)}
                      className="w-full rounded-2xl border border-slate-200 bg-white px-3 py-3 text-left transition hover:border-slate-300 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-slate-700"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">{scorecard.label}</div>
                          <div className="text-xs text-slate-500 dark:text-slate-400">{successRate}% completed across {scorecard.session_count} runs</div>
                        </div>
                        <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", scorecard.friction_count > 0 ? pulseTagClasses("friction") : pulseTagClasses("recovered"))}>
                          {scorecard.friction_count > 0 ? `${scorecard.friction_count} friction` : "steady"}
                        </span>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500 dark:text-slate-400">
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">{scorecard.error_count} errors</span>
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">{scorecard.tool_friction_count} tool friction</span>
                        <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">{scorecard.instruction_drift_count} drift</span>
                        {runtimeLabel && <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">{runtimeLabel}</span>}
                      </div>
                      {(scorecard.top_issue || scorecard.top_root_cause) && (
                        <div className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                          {scorecard.top_issue ?? "Primary friction trend"}{scorecard.top_root_cause ? ` \u00b7 ${rootCauseLabel(scorecard.top_root_cause)}` : ""}
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
  );
}

// --- SessionDetailsPanel ---

export function SessionDetailsPanel({
  details,
  previewCount,
  issueMarkers,
  activeIssueTag,
}: {
  details: SessionEventDetailsState | undefined;
  previewCount: number;
  issueMarkers: PersonaIssueMarker[];
  activeIssueTag: string | null;
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
      <div className="mt-3 flex items-center gap-2 border-t border-slate-200 pt-3 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" />Loading full session detail\u2026
      </div>
    );
  }
  if (details.error) {
    return <div className="mt-3 rounded-2xl border border-rose-200 bg-rose-50 px-3 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-300">{details.error}</div>;
  }
  if (details.events.length === 0) {
    return <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-500 dark:border-slate-800 dark:bg-slate-950/50 dark:text-slate-400">No additional detail was recorded for this session.</div>;
  }

  const totalHiddenCount = Math.max(blocks.length - visibleImportantBlocks.length, 0);
  const errorCount = blocks.filter((b) => b.eventType === "error").length;
  const toolActivityCount = blocks.filter((b) => b.eventType === "tool_use" || b.eventType === "tool_result").length;
  const issueCount = filteredIssueMarkers.length;
  const visibleSectionTitle = showFullTrace ? "Full trace" : "Important events";
  const visibleSectionDescription = showFullTrace
    ? "Every recorded step is shown below in chronological order."
    : "Only the highest-signal steps are shown first. Routine chatter stays hidden until you ask for it.";
  const visibleBlocks = showFullTrace ? blocks : visibleImportantBlocks;
  const totalSummaryMarkers = previewCount > 0 ? `${previewCount} summary marker${previewCount === 1 ? "" : "s"}` : null;
  const overviewBadges = [
    `${blocks.length} event${blocks.length === 1 ? "" : "s"} recorded`,
    `${visibleImportantBlocks.length} key event${visibleImportantBlocks.length === 1 ? "" : "s"} surfaced`,
    issueCount > 0 ? `${issueCount} issue${issueCount === 1 ? "" : "s"} highlighted` : "No issue markers",
    totalHiddenCount > 0 ? `${totalHiddenCount} routine item${totalHiddenCount === 1 ? "" : "s"} hidden` : "No routine items hidden",
    toolActivityCount > 0 ? `${toolActivityCount} tool step${toolActivityCount === 1 ? "" : "s"}` : null,
    errorCount > 0 ? `${errorCount} error${errorCount === 1 ? "" : "s"}` : "No errors recorded",
    totalSummaryMarkers,
  ].filter((v): v is string => Boolean(v));

  return (
    <div className="mt-3 space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
      <section className="space-y-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">Overview</div>
        <div className="rounded-2xl border border-slate-200 bg-slate-50/90 px-3 py-3 text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950/60 dark:text-slate-300">
          <div className="flex flex-wrap gap-2">
            {overviewBadges.map((badge) => (
              <span key={badge} className={cn("rounded-full px-2.5 py-1 text-xs font-medium",
                badge.toLowerCase().includes("error") && !badge.toLowerCase().includes("no errors")
                  ? outcomeToneClasses(true) : "bg-slate-200/80 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
              )}>{badge}</span>
            ))}
          </div>
        </div>
      </section>

      {filteredIssueMarkers.length > 0 && (
        <section className="space-y-2">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">Issues</div>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">The events below are the most likely sources of friction or failure in this run.</p>
          </div>
          <div className="space-y-2">
            {issueBlocks.length > 0 ? (
              issueBlocks.slice(0, 4).map((b) => <SessionDetailBlockCard key={`issue-${b.id}`} block={b} />)
            ) : (
              filteredIssueMarkers.slice(0, 4).map((marker) => (
                <div key={`issue-marker-${marker.event_id}-${marker.primary_tag}`} className="rounded-xl border border-slate-200 bg-slate-50/90 px-3 py-3 dark:border-slate-800 dark:bg-slate-950/50">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", pulseTagClasses(marker.primary_tag))}>{pulseTagLabel(marker.primary_tag)}</span>
                    {marker.primary_root_cause && <span className={cn("rounded-full px-2 py-0.5 text-[11px]", rootCauseClasses(marker.primary_root_cause))}>{rootCauseLabel(marker.primary_root_cause)}</span>}
                  </div>
                  <div className="mt-2 text-sm font-semibold text-slate-900 dark:text-slate-100">{marker.title}</div>
                  <ExpandableText text={marker.summary} expandedText={marker.detail} className="mt-1 block whitespace-pre-wrap break-words text-sm text-slate-600 dark:text-slate-300" collapsedLength={220} />
                </div>
              ))
            )}
          </div>
        </section>
      )}

      <section className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400 dark:text-slate-500">{visibleSectionTitle}</div>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{visibleSectionDescription}</p>
          </div>
          {blocks.length > visibleImportantBlocks.length && (
            <button type="button" onClick={() => setShowFullTrace((c) => !c)}
              className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:text-slate-900 dark:border-slate-700 dark:text-slate-300 dark:hover:border-slate-500 dark:hover:text-white"
            >
              {showFullTrace ? <><ChevronUp className="h-3.5 w-3.5" />Show key events</> : <><ChevronDown className="h-3.5 w-3.5" />Show full trace ({blocks.length} events)</>}
            </button>
          )}
        </div>
        <div className="space-y-2">
          {visibleBlocks.map((b) => <SessionDetailBlockCard key={b.id} block={b} />)}
        </div>
      </section>
    </div>
  );
}

// --- RoutineHeartbeatGroup ---

export function RoutineHeartbeatGroup({
  block, expanded, onToggle, activeSessionId, activeIssueTag,
  expandedEntryIds, onToggleEntry, sessionEventDetails,
}: {
  block: RoutineHeartbeatTimelineBlock; expanded: boolean; onToggle: () => void;
  activeSessionId: string | null; activeIssueTag: string | null;
  expandedEntryIds: Record<string, boolean>;
  onToggleEntry: (entryId: string, sessionId: string) => void;
  sessionEventDetails: Record<string, SessionEventDetailsState>;
}) {
  const first = block.items[0]?.anchorItem;
  const last = block.items.at(-1)?.anchorItem;
  const timeRange = first && last ? `${formatTimeLabel(first.timestamp)} to ${formatTimeLabel(last.timestamp)}` : null;

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/90 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/80">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-slate-100">
              <Clock3 className="h-4 w-4 text-slate-400" />{block.items.length} routine heartbeats
            </span>
            {timeRange && <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300">{timeRange}</span>}
          </div>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Routine checks stay collapsed until you need the full detail.</p>
        </div>
        <button type="button" onClick={onToggle}
          className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-white dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {expanded ? "Hide routine checks" : "Show routine checks"}
        </button>
      </div>
      {expanded && (
        <div className="mt-3 space-y-3 border-t border-slate-200 pt-3 dark:border-slate-800">
          {block.items.map(({ anchorItem }) => (
            <div key={anchorItem.id} data-session-anchor={anchorItem.sessionId} data-testid="stream-item" data-stream-item-id={anchorItem.id} data-timestamp={anchorItem.timestamp.toISOString()} className="flex items-start gap-3">
              <TimelineTimestamp timestamp={anchorItem.timestamp} />
              <div className="min-w-0 flex-1">
                <HeartbeatCard entry={anchorItem.entry} activeIssueTag={activeIssueTag} selected={anchorItem.sessionId === activeSessionId}
                  expanded={!!expandedEntryIds[anchorItem.id]} onToggle={() => onToggleEntry(anchorItem.id, anchorItem.sessionId)}
                  details={sessionEventDetails[anchorItem.sessionId]} />
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
}: {
  childRuns: FeedChildRun[]; activeSessionId: string | null; activeIssueTag: string | null;
  expandedEntryIds: Record<string, boolean>;
  onToggle: (entryId: string, sessionId: string) => void;
  matchedIds: Set<string>; activeMatchId: string | null;
  sessionEventDetails: Record<string, SessionEventDetailsState>;
}) {
  return (
    <div className="ml-5 mt-3 border-l border-dashed border-sky-200 pl-4 dark:border-sky-900">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-600 dark:text-sky-300">Spawned Agents</div>
      <div className="space-y-3">
        {childRuns.map((childRun) => (
          <div key={childRun.id} data-session-anchor={childRun.sessionId} data-testid="stream-item" data-stream-item-id={childRun.id} data-timestamp={childRun.timestamp.toISOString()}
            className={cn("flex items-start gap-3 rounded-2xl",
              matchedIds.has(childRun.id) && "px-2 py-1 ring-1 ring-amber-200 dark:ring-amber-800",
              activeMatchId === childRun.id && "ring-2 ring-amber-400 dark:ring-amber-500",
            )}
          >
            <TimelineTimestamp timestamp={childRun.timestamp} />
            <div className="min-w-0 flex-1">
              <ChildRunCard entry={childRun.entry} activeIssueTag={activeIssueTag} selected={childRun.sessionId === activeSessionId}
                expanded={!!expandedEntryIds[childRun.id]} onToggle={() => onToggle(childRun.id, childRun.sessionId)}
                details={sessionEventDetails[childRun.sessionId]} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- ChildRunCard ---

export function ChildRunCard({
  entry, activeIssueTag, selected, expanded, onToggle, details,
}: {
  entry: PersonaStreamEntry; activeIssueTag: string | null; selected: boolean; expanded: boolean;
  onToggle: () => void; details?: SessionEventDetailsState;
}) {
  const issueMarkers = visibleIssueMarkers(entry, activeIssueTag);
  const showPulseSummary = shouldRenderPulseSummary(entry.pulse_summary, issueMarkers);
  const primaryIssue = issueMarkers[0];
  const visiblePulseTags = entry.pulse_tags.filter((tag) => tag !== "friction" && tag !== primaryIssue?.primary_tag);
  const visibleRootCauses = entry.root_causes.filter((rc) => rc !== primaryIssue?.primary_root_cause);

  return (
    <div className={cn("rounded-2xl border px-4 py-3", selected ? "border-sky-300 bg-sky-50/70 dark:border-sky-700 dark:bg-sky-950/30" : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900")}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-full bg-sky-100 p-2 text-sky-700 dark:bg-sky-950/50 dark:text-sky-300"><Bot className="h-4 w-4" /></div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">{entry.agent_slug || "Agent"} on {entry.project_id}</span>
            <span className={cn("rounded-full px-2 py-0.5 text-[11px]", entryStatusClasses(entry.status))}>{entry.status}</span>
            {entry.tool_count > 0 && <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 dark:bg-amber-950/40 dark:text-amber-300"><Wrench className="h-3 w-3" />{entry.tool_count}</span>}
          </div>
          <ExpandableText text={entry.summary_oneliner || entry.live_summary || "Child run activity"} className="mt-1 block text-sm text-slate-600 dark:text-slate-300" collapsedLength={220} />
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400 dark:text-slate-500">
            {entry.external_id && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">task {entry.external_id}</span>}
            {entry.current_branch && <span className="rounded-full bg-slate-100 px-2 py-0.5 dark:bg-slate-800">{entry.current_branch}</span>}
            {visiblePulseTags.map((tag) => <span key={`${entry.session_id}-${tag}`} className={cn("rounded-full px-2 py-0.5", pulseTagClasses(tag))}>{pulseTagLabel(tag)}</span>)}
            {visibleRootCauses.map((rc) => <span key={`${entry.session_id}-${rc}`} className={cn("rounded-full px-2 py-0.5", rootCauseClasses(rc))}>{rootCauseLabel(rc)}</span>)}
          </div>
          {showPulseSummary && entry.pulse_summary && <ExpandableText text={entry.pulse_summary} className="mt-2 block text-xs text-slate-500 dark:text-slate-400" collapsedLength={180} />}
          <EntryIssueSummary issueMarkers={issueMarkers} />
          {(entry.event_previews.length > 0 || details) && (
            <button type="button" onClick={onToggle} className="mt-3 inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}{expanded ? "Hide run details" : "Show run details"}
            </button>
          )}
          {expanded && <SessionDetailsPanel details={details} previewCount={entry.event_previews.length} issueMarkers={issueMarkers} activeIssueTag={activeIssueTag} />}
        </div>
      </div>
    </div>
  );
}

// --- HeartbeatCard ---

export function HeartbeatCard({
  entry, activeIssueTag, selected, expanded, onToggle, details,
}: {
  entry: PersonaStreamEntry; activeIssueTag: string | null; selected: boolean; expanded: boolean;
  onToggle: () => void; details?: SessionEventDetailsState;
}) {
  const issueMarkers = visibleIssueMarkers(entry, activeIssueTag);
  const showPulseSummary = shouldRenderPulseSummary(entry.pulse_summary, issueMarkers);
  const primaryIssue = issueMarkers[0];
  const visiblePulseTags = entry.pulse_tags.filter((tag) => tag !== "friction" && tag !== primaryIssue?.primary_tag);
  const visibleRootCauses = entry.root_causes.filter((rc) => rc !== primaryIssue?.primary_root_cause);

  return (
    <div className={cn("rounded-2xl border px-4 py-3", selected ? "border-amber-300 bg-amber-50/80 dark:border-amber-700 dark:bg-amber-950/30" : "border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900")}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-full bg-amber-100 p-2 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300"><HeartPulse className="h-4 w-4" /></div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">Heartbeat</span>
            <span className={cn("rounded-full px-2 py-0.5 text-[11px]", entryStatusClasses(entry.status))}>{entry.status}</span>
            {entry.tool_count > 0 && <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700 dark:bg-amber-950/40 dark:text-amber-300"><Wrench className="h-3 w-3" />{entry.tool_count}</span>}
          </div>
          <ExpandableText text={entry.summary_oneliner || entry.live_summary || "Routine check completed"} className="mt-1 block text-sm text-slate-600 dark:text-slate-300" collapsedLength={220} />
          {entry.live_summary && entry.summary_oneliner !== entry.live_summary && !isGenericStatusText(entry.live_summary) && (
            <ExpandableText text={entry.live_summary} className="mt-2 block text-xs text-slate-400 dark:text-slate-500" collapsedLength={180} />
          )}
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-400 dark:text-slate-500">
            {entry.external_id && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">{entry.external_id}</span>}
            {visiblePulseTags.map((tag) => <span key={`${entry.session_id}-${tag}`} className={cn("rounded-full px-2 py-0.5", pulseTagClasses(tag))}>{pulseTagLabel(tag)}</span>)}
            {visibleRootCauses.map((rc) => <span key={`${entry.session_id}-${rc}`} className={cn("rounded-full px-2 py-0.5", rootCauseClasses(rc))}>{rootCauseLabel(rc)}</span>)}
          </div>
          {showPulseSummary && entry.pulse_summary && <ExpandableText text={entry.pulse_summary} className="mt-2 block text-xs text-slate-500 dark:text-slate-400" collapsedLength={180} />}
          <EntryIssueSummary issueMarkers={issueMarkers} />
          {(entry.event_previews.length > 0 || details) && (
            <button type="button" onClick={onToggle} className="mt-3 inline-flex items-center gap-1 rounded-full border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800">
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}{expanded ? "Hide heartbeat details" : "Show heartbeat details"}
            </button>
          )}
          {expanded && <SessionDetailsPanel details={details} previewCount={entry.event_previews.length} issueMarkers={issueMarkers} activeIssueTag={activeIssueTag} />}
        </div>
      </div>
    </div>
  );
}
