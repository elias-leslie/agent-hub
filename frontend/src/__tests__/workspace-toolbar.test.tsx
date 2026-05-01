import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceToolbar } from "@/app/persona/components/WorkspaceToolbar";
import type { FilterMode } from "@/app/persona/components/pulse-helpers";

const FILTER_COUNTS: Record<FilterMode, number> = {
  all: 0,
  messages: 0,
  work: 0,
  heartbeats: 0,
  friction: 0,
  errors: 0,
  warnings: 0,
  stalled: 0,
  drift: 0,
  tool_friction: 0,
  retries: 0,
  recovered: 0,
  escalations: 0,
};

function renderToolbar() {
  return render(
    <WorkspaceToolbar
      search=""
      onSearchChange={vi.fn()}
      timeRange="24h"
      onTimeRangeChange={vi.fn()}
      filterMode="all"
      setFilterMode={vi.fn()}
      showFilters={false}
      setShowFilters={vi.fn()}
      filterCounts={FILTER_COUNTS}
      deferredSearch=""
      matchCount={0}
      activeSearchMatch={0}
      visibleSearchMatches={[]}
      activeMatchId={null}
      onJumpToMatch={vi.fn()}
      onSelectMatch={vi.fn()}
    />,
  );
}

describe("WorkspaceToolbar", () => {
  it("wraps mobile controls instead of forcing the range and filter buttons offscreen", () => {
    renderToolbar();

    expect(screen.getByTestId("workspace-toolbar-controls")).toHaveClass("flex-wrap", "sm:flex-nowrap");
    expect(screen.getByPlaceholderText("Search history, tasks, files, agents...").parentElement).toHaveClass(
      "basis-full",
      "sm:basis-auto",
    );
    expect(screen.getByRole("button", { name: /24h/i }).parentElement).toHaveClass("shrink-0");
    expect(screen.getByTitle("Toggle filters")).toHaveClass("shrink-0");
  });
});
