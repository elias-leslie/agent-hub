import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PersonaRunHud } from "@/app/persona/components/PersonaRunHud";

describe("PersonaRunHud", () => {
  it("surfaces the current blocker alongside the main run stats", () => {
    render(
      <PersonaRunHud
        personaName="Avery"
        runtime={{
          primarySession: {
            id: "sess-1",
            project_id: "agent-hub",
            provider: "codex",
            model: "codex/gpt-5.4",
            status: "active",
            agent_slug: "persona",
            session_type: "completion",
            parent_session_id: null,
            external_id: null,
            current_branch: "main",
            live_activity: {
              phase: "running_tool",
              status: "active",
              summary: "Running validation",
              health: "ok",
              stalled: true,
              current_tool_name: "bash",
              stall_reason: "Execution permission denied",
              outstanding_tool_calls: 1,
              tool_calls_count: 2,
              files_touched: ["frontend/src/app/persona/page.tsx"],
            },
            message_count: 0,
            total_input_tokens: 0,
            total_output_tokens: 0,
            created_at: "2026-04-16T15:00:00Z",
            updated_at: "2026-04-16T15:01:00Z",
          },
          primarySessionDetails: null,
          activePersonaSessions: [],
          activeChildSessions: [],
          loading: false,
          error: "Background refresh failed",
          stoppingSessionId: null,
          runtimeSyncKey: "sync-1",
          refresh: vi.fn(),
          stopSession: vi.fn(),
          stopCurrentStream: vi.fn(),
          stopActiveWork: vi.fn(),
        } as never}
        onRefresh={vi.fn()}
        onOpenCommands={vi.fn()}
      />,
    );

    expect(screen.getByText("Blocker")).toBeInTheDocument();
    expect(screen.getAllByText(/Execution permission denied/i)).toHaveLength(2);
  });
});
