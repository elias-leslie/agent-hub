"use client";

import { useEffect, useMemo, useState } from "react";
import type { ChatMessage, StreamStatus } from "@agent-hub/chat-ui";

import { cn } from "@/lib/utils";
import type { Persona } from "@/types/persona";
import type { Session, SessionListItem } from "@/lib/api/sessions";
import { toSessionListItem, type PersonaRuntimeState } from "../hooks/usePersonaRuntime";
import { useWorkspaceState } from "./useWorkspaceState";
import { PersonaOperatorDeck, type PersonaOperatorTab } from "./PersonaOperatorDeck";
import { PersonaThreadHeader } from "./PersonaThreadHeader";
import { WorkspaceToolbar } from "./WorkspaceToolbar";
import { WorkspaceTimeline } from "./WorkspaceTimeline";
import { WorkspaceChatFooter } from "./WorkspaceChatFooter";

function getLatestAssistantMessage(messages: ChatMessage[]): ChatMessage | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "assistant") {
      return messages[index];
    }
  }
  return null;
}

function buildDraftSession(
  sessionId: string,
  projectId: string,
  status: StreamStatus,
  responseStatusLabel: string | null,
  messages: ChatMessage[],
): SessionListItem {
  const latestAssistant = getLatestAssistantMessage(messages);
  const runningTool = latestAssistant?.toolExecutions?.find((tool) => tool.status === "running") ?? null;
  const now = new Date().toISOString();
  const liveStatus = status === "error" ? "error" : "active";
  const phase =
    status === "error"
      ? "error"
      : runningTool
        ? "running_tool"
        : "waiting_for_model";
  const summary =
    runningTool
      ? `Running ${runningTool.name}`
      : responseStatusLabel
        ?? "Waiting for model response";
  return {
    id: sessionId,
    project_id: projectId,
    provider: latestAssistant?.agentProvider ?? "openai",
    model: latestAssistant?.agentModel ?? "unknown",
    status: liveStatus === "error" ? "failed" : "active",
    agent_slug: "persona",
    session_type: "chat",
    parent_session_id: null,
    external_id: null,
    current_branch: null,
    live_activity: {
      phase,
      status: liveStatus,
      summary,
      health: liveStatus === "error" ? "error" : "ok",
      stalled: false,
      current_tool_name: runningTool?.name ?? null,
      last_tool_name: runningTool?.name ?? null,
      outstanding_tool_calls: runningTool ? 1 : 0,
      tool_calls_count: latestAssistant?.toolExecutions?.length ?? 0,
      files_touched: [],
    },
    message_count: messages.length,
    total_input_tokens: latestAssistant?.inputTokens ?? 0,
    total_output_tokens: latestAssistant?.outputTokens ?? 0,
    created_at: latestAssistant?.timestamp.toISOString() ?? now,
    updated_at: now,
  };
}

function isActiveChatStream(status: StreamStatus): boolean {
  return status === "connecting" || status === "streaming" || status === "reconnecting" || status === "cancelling";
}

interface UnifiedPersonaWorkspaceProps {
  persona?: Persona;
  agentSlug: string;
  personaName?: string;
  runtime?: PersonaRuntimeState;
  activeSessionId: string | null;
  sidebarRefreshTrigger: number;
  runtimeSyncKey: string;
  onSelectSession: (sessionId: string | null) => void;
  onSessionCreated: (sessionId: string) => void;
  onNewSession: () => void;
}

export function UnifiedPersonaWorkspace(props: UnifiedPersonaWorkspaceProps) {
  const focusedRuntimeSession = useMemo(() => {
    if (!props.runtime || !props.activeSessionId) {
      return null;
    }
    const sessions = [props.runtime.primarySession, ...props.runtime.activeChildSessions].filter(
      (session): session is NonNullable<typeof session> => Boolean(session),
    );
    return sessions.find((session) => session.id === props.activeSessionId) ?? null;
  }, [props.activeSessionId, props.runtime]);
  const persistedSessionProjectId = props.runtime?.primarySessionDetails?.project_id ?? null;
  const sessionProjectId = focusedRuntimeSession?.project_id ?? persistedSessionProjectId ?? null;
  const [selectedProjectId, setSelectedProjectId] = useState(sessionProjectId ?? "agent-hub");
  const [activeOperatorTab, setActiveOperatorTab] = useState<PersonaOperatorTab>("workflow");
  const [deskOpen, setDeskOpen] = useState(() => (typeof window !== "undefined" ? window.innerWidth >= 1024 : false));
  const [compactViewport, setCompactViewport] = useState(false);
  const state = useWorkspaceState({
    ...props,
    targetProjectId: selectedProjectId,
    sessionProjectId,
  });
  const optimisticDraftActive = isActiveChatStream(state.status);
  const persistedDisplaySession = useMemo(() => {
    if (!props.runtime?.primarySessionDetails) {
      return null;
    }
    return toSessionListItem(props.runtime.primarySessionDetails);
  }, [props.runtime?.primarySessionDetails]);
  const displaySession = useMemo(() => {
    if (!props.runtime) {
      return null;
    }
    const selectedSessionId = state.selectedSessionId ?? state.currentSessionId;
    const shouldPreferDraftForSelectedSession = Boolean(
      optimisticDraftActive
      && state.currentSessionId
      && selectedSessionId
      && selectedSessionId === state.currentSessionId,
    );
    const runtimeSessions = [
      props.runtime.primarySession,
      ...props.runtime.activePersonaSessions,
      ...props.runtime.activeChildSessions,
    ].filter((session): session is SessionListItem => Boolean(session));
    if (shouldPreferDraftForSelectedSession) {
      return buildDraftSession(
        state.currentSessionId!,
        sessionProjectId ?? selectedProjectId,
        state.status,
        state.responseStatusLabel,
        state.messages,
      );
    }
    if (selectedSessionId) {
      const matchedSession = runtimeSessions.find((session) => session.id === selectedSessionId);
      if (matchedSession) {
        return matchedSession;
      }
      if (persistedDisplaySession?.id === selectedSessionId) {
        return persistedDisplaySession;
      }
    }
    if (
      state.currentSessionId &&
      persistedDisplaySession?.id === state.currentSessionId &&
      (!selectedSessionId || selectedSessionId === state.currentSessionId) &&
      !optimisticDraftActive
    ) {
      return persistedDisplaySession;
    }
    if (state.currentSessionId && (!selectedSessionId || selectedSessionId === state.currentSessionId)) {
      return buildDraftSession(
        state.currentSessionId,
        sessionProjectId ?? selectedProjectId,
        state.status,
        state.responseStatusLabel,
        state.messages,
      );
    }
    if (optimisticDraftActive && !state.selectedSessionId) {
      return buildDraftSession(
        "__live_draft__",
        selectedProjectId,
        state.status,
        state.responseStatusLabel,
        state.messages,
      );
    }
    return props.runtime.primarySession ?? persistedDisplaySession;
  }, [
    optimisticDraftActive,
    persistedDisplaySession,
    props.runtime,
    selectedProjectId,
    sessionProjectId,
    state.currentSessionId,
    state.messages,
    state.responseStatusLabel,
    state.selectedSessionId,
    state.status,
  ]);
  const displaySessionDetails = useMemo(() => {
    if (!displaySession || !props.runtime?.primarySessionDetails) {
      return null;
    }
    return props.runtime.primarySessionDetails.id === displaySession.id ? props.runtime.primarySessionDetails : null;
  }, [displaySession, props.runtime?.primarySessionDetails]);
  const isTerminalThread =
    Boolean(
      displaySession
      && displaySession.agent_slug === "persona"
      && !displaySession.parent_session_id
      && displaySession.status !== "active"
      && displaySession.live_activity?.status !== "active"
      && !["waiting_for_model", "running_tool", "finalizing"].includes(displaySession.live_activity?.phase ?? ""),
    );
  const isDraftDisplaySession = Boolean(
    displaySession
    && (
      displaySession.id === "__live_draft__"
      || (optimisticDraftActive && state.currentSessionId && displaySession.id === state.currentSessionId)
    ),
  );
  const threadSource = displaySession || state.messages.length > 0
    ? (isDraftDisplaySession ? "draft" : "session")
    : null;
  const handleStopDisplaySession = () => {
    if (!props.runtime) {
      return;
    }
    if (state.currentSessionId) {
      void props.runtime.stopSession(state.currentSessionId);
      return;
    }
    if (optimisticDraftActive) {
      state.cancelStream();
      return;
    }
    if (displaySession) {
      void props.runtime.stopSession(displaySession.id);
      return;
    }
    void props.runtime.stopCurrentStream();
  };

  useEffect(() => {
    if (sessionProjectId) {
      setSelectedProjectId(sessionProjectId);
    }
  }, [sessionProjectId]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const updateCompactViewport = () => {
      const isCompact = window.innerHeight < 720;
      setCompactViewport(isCompact);
      if (window.innerWidth >= 1024) {
        setDeskOpen(true);
      }
    };
    updateCompactViewport();
    window.addEventListener("resize", updateCompactViewport);
    return () => window.removeEventListener("resize", updateCompactViewport);
  }, []);

  const handleNewThread = () => {
    state.resetSession();
    props.onNewSession();
  };

  const footerThreadSessionId =
    state.selectedSessionId
    ?? state.currentSessionId
    ?? props.activeSessionId
    ?? null;
  const showJumpToLatest = Boolean(
    state.latestItemId && (!state.isAtBottom || !state.autoFollow || state.newActivityCount > 0),
  );
  const jumpToLatestLabel = showJumpToLatest
    ? state.newActivityCount > 0
      ? `${state.newActivityCount} new ${state.newActivityCount === 1 ? "item" : "items"} · Jump to latest`
      : "Jump to latest"
    : null;

  return (
    <div
      data-testid="persona-workspace-root"
      data-compact-viewport={compactViewport ? "true" : "false"}
      className="relative flex h-full min-h-0 flex-col overflow-hidden"
    >
      <WorkspaceToolbar
        search={state.search}
        onSearchChange={(value) => {
          state.setSearch(value);
          state.setAnchorEntryId(null);
        }}
        timeRange={state.timeRange}
        onTimeRangeChange={state.setTimeRange}
        filterMode={state.filterMode}
        setFilterMode={state.setFilterMode}
        showFilters={state.showFilters}
        setShowFilters={state.setShowFilters}
        filterCounts={state.filterCounts}
        deferredSearch={state.deferredSearch}
        matchCount={state.matchCount}
        activeSearchMatch={state.activeSearchMatch}
        visibleSearchMatches={state.visibleSearchMatches}
        activeMatchId={state.activeMatchId}
        onJumpToMatch={state.jumpToSearchMatch}
        onSelectMatch={(entryId) => {
          state.setAnchorEntryId(entryId);
        }}
      />

      {props.persona && props.runtime ? (
        <PersonaThreadHeader
          runtime={props.runtime}
          focusSession={displaySession}
          selectedSessionId={state.selectedSessionId}
          targetProjectId={selectedProjectId}
          threadSource={threadSource}
          onSelectSession={props.onSelectSession}
          activeTab={activeOperatorTab}
          onOpenTab={(tab) => setActiveOperatorTab(tab)}
          onNewThread={handleNewThread}
          deskOpen={deskOpen}
          onToggleDesk={() => setDeskOpen((current) => !current)}
          compactViewport={compactViewport}
        />
      ) : null}

      <div data-testid="persona-workspace-main" className="min-h-0 flex-1 overflow-hidden lg:grid lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <WorkspaceTimeline
            scrollRef={state.scrollRef}
            loading={state.loading}
            error={state.error}
            chatError={state.chatError}
            groupedItems={state.groupedItems}
            timelineRows={state.timelineRows}
            virtualizer={state.virtualizer}
            visiblePulseMetrics={state.visiblePulseMetrics}
            pulse={state.pulse}
            applyPulseFilter={state.applyPulseFilter}
            inspectAgentPulse={state.inspectAgentPulse}
            selectedSessionId={state.selectedSessionId}
            activeIssueTag={state.activeIssueTag}
            expandedEntryIds={state.expandedEntryIds}
            expandedRoutineGroupIds={state.expandedRoutineGroupIds}
            matchedIds={state.matchedIds}
            activeMatchId={state.activeMatchId}
            sessionEventDetails={state.sessionEventDetails}
            narrationCache={state.narrationCache}
            fetchNarrationTags={state.fetchNarrationTags}
            personaDisplayName={state.personaDisplayName}
            total={state.total}
            entries={state.entries}
            deferredSearch={state.deferredSearch}
            status={state.status}
            autoFollow={state.autoFollow}
            isAtBottom={state.isAtBottom}
            newActivityCount={state.newActivityCount}
            latestItemId={state.latestItemId}
            onToggleEntry={state.toggleExpanded}
            onToggleRoutineGroup={state.toggleRoutineGroup}
            onLoadOlder={state.handleLoadOlder}
            onJumpToLatest={state.handleJumpToLatest}
            showPulseOverview={!(props.persona && props.runtime)}
            compactViewport={compactViewport}
          />
        </div>

        {props.persona && props.runtime ? (
          <aside className="hidden min-h-0 overflow-hidden border-l border-slate-800/60 lg:flex lg:w-[320px] lg:min-w-[320px] lg:max-w-[320px]">
            <PersonaOperatorDeck
              persona={props.persona}
              personaName={state.personaDisplayName}
              runtime={props.runtime}
              focusSession={displaySession}
              focusSessionDetails={displaySessionDetails}
              onStopFocusSession={handleStopDisplaySession}
              entries={state.hydratedEntries}
              pulse={state.pulse}
              visiblePulseMetrics={state.visiblePulseMetrics}
              activeSessionId={state.selectedSessionId}
              selectedProjectId={selectedProjectId}
              onProjectChange={setSelectedProjectId}
              onSelectSession={props.onSelectSession}
              sendMessage={state.sendMessage}
              applyPulseFilter={state.applyPulseFilter}
              inspectAgentPulse={state.inspectAgentPulse}
              activeTab={activeOperatorTab}
              onTabChange={setActiveOperatorTab}
            />
          </aside>
        ) : null}
      </div>

      {props.persona && props.runtime && deskOpen ? (
        <div className="fixed inset-0 z-40 bg-slate-950/70 backdrop-blur-sm lg:hidden">
          <button
            type="button"
            aria-label="Close desk"
            onClick={() => setDeskOpen(false)}
            className="absolute inset-0"
          />
          <div className="absolute inset-y-0 right-0 w-full max-w-[26rem] overflow-hidden border-l border-slate-800/70 bg-[#07090d] shadow-[0_28px_80px_-36px_rgba(15,23,42,0.95)]">
            <PersonaOperatorDeck
              persona={props.persona}
              personaName={state.personaDisplayName}
              runtime={props.runtime}
              focusSession={displaySession}
              focusSessionDetails={displaySessionDetails}
              onStopFocusSession={handleStopDisplaySession}
              entries={state.hydratedEntries}
              pulse={state.pulse}
              visiblePulseMetrics={state.visiblePulseMetrics}
              activeSessionId={state.selectedSessionId}
              selectedProjectId={selectedProjectId}
              onProjectChange={setSelectedProjectId}
              onSelectSession={props.onSelectSession}
              sendMessage={state.sendMessage}
              applyPulseFilter={state.applyPulseFilter}
              inspectAgentPulse={state.inspectAgentPulse}
              activeTab={activeOperatorTab}
              onTabChange={setActiveOperatorTab}
              layout="stacked"
            />
          </div>
        </div>
      ) : null}

      <div
        data-testid="persona-footer-shell"
        className={cn(compactViewport && "absolute inset-x-0 bottom-0 z-30")}
      >
        <WorkspaceChatFooter
          personaDisplayName={state.personaDisplayName}
          responseStatusLabel={state.responseStatusLabel}
          status={state.status}
          targetProjectId={selectedProjectId}
          sessionProjectId={sessionProjectId}
          threadSessionId={footerThreadSessionId}
          threadSource={threadSource}
          isTerminalThread={isTerminalThread}
          sendMessage={state.sendMessage}
          cancelStream={state.cancelStream}
          preferencesEndpoint={state.apiConfig.preferencesEndpoint}
          onNewSession={handleNewThread}
          compactViewport={compactViewport}
          jumpToLatestLabel={jumpToLatestLabel}
          onJumpToLatest={jumpToLatestLabel ? state.handleJumpToLatest : undefined}
          showNewThread={!props.persona || !props.runtime}
        />
      </div>
    </div>
  );
}
