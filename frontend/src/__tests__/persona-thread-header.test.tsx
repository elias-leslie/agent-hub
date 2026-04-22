import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PersonaThreadHeader } from "@/app/persona/components/PersonaThreadHeader";

describe("PersonaThreadHeader", () => {
  it("marks draft and persisted thread provenance explicitly", () => {
    render(
      <PersonaThreadHeader
        personaName="Avery"
        runtime={{
          primarySession: null,
          primarySessionDetails: null,
          activePersonaSessions: [],
          activeChildSessions: [],
          loading: false,
          error: null,
          stoppingSessionId: null,
          runtimeSyncKey: "sync-1",
          refresh: vi.fn().mockResolvedValue(undefined),
          stopSession: vi.fn().mockResolvedValue(true),
          stopCurrentStream: vi.fn().mockResolvedValue(true),
          stopActiveWork: vi.fn().mockResolvedValue({ cancelled: 0, attempted: 0 }),
        }}
        focusSession={{
          id: "sess-1",
          project_id: "summitflow",
          provider: "codex",
          model: "codex/gpt-5.4",
          status: "completed",
          agent_slug: "persona",
          session_type: "chat",
          parent_session_id: null,
          external_id: null,
          current_branch: null,
          live_activity: {
            phase: "completed",
            status: "completed",
            summary: "Session closed",
            health: "completed",
            stalled: false,
            current_tool_name: null,
            last_tool_name: "bash",
            outstanding_tool_calls: 0,
            tool_calls_count: 1,
            files_touched: [],
          },
          message_count: 4,
          total_input_tokens: 0,
          total_output_tokens: 0,
          created_at: "2026-04-15T23:44:07.068073Z",
          updated_at: "2026-04-15T23:48:07.970724Z",
        }}
        selectedSessionId="sess-1"
        targetProjectId="agent-hub"
        threadSource="session"
        onSelectSession={vi.fn()}
        sendMessage={vi.fn()}
        activeTab="workflow"
        onOpenTab={vi.fn()}
        deskOpen
        onToggleDesk={vi.fn()}
      />,
    );

    expect(screen.getByText("Session")).toBeInTheDocument();
    expect(screen.getByText("Reply continues here")).toBeInTheDocument();
    expect(screen.getByText("Project · summitflow")).toBeInTheDocument();
  });
});
