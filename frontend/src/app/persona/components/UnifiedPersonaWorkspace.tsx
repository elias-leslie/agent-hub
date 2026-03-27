"use client";

import { useWorkspaceState } from "./useWorkspaceState";
import { WorkspaceToolbar } from "./WorkspaceToolbar";
import { WorkspaceTimeline } from "./WorkspaceTimeline";
import { WorkspaceChatFooter } from "./WorkspaceChatFooter";

interface UnifiedPersonaWorkspaceProps {
  agentSlug: string;
  personaName?: string;
  activeSessionId: string | null;
  sidebarRefreshTrigger: number;
  runtimeSyncKey: string;
  onSelectSession: (sessionId: string | null) => void;
  onSessionCreated: (sessionId: string) => void;
  onNewSession: () => void;
}

export function UnifiedPersonaWorkspace(props: UnifiedPersonaWorkspaceProps) {
  const state = useWorkspaceState(props);

  return (
    <div className="relative flex h-full min-h-0 flex-col">
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
      />

      <WorkspaceChatFooter
        responseStatusLabel={state.responseStatusLabel}
        status={state.status}
        sendMessage={state.sendMessage}
        cancelStream={state.cancelStream}
        preferencesEndpoint={state.apiConfig.preferencesEndpoint}
        onNewSession={props.onNewSession}
      />
    </div>
  );
}
