import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PersonaBlockerPanel } from "@/app/persona/components/PersonaBlockerPanel";

describe("PersonaBlockerPanel", () => {
  it("orders hard blockers first and labels prompt budget as preview-derived", () => {
    render(
      <PersonaBlockerPanel
        executionState="active"
        heartbeatIntervalMinutes={30}
        selectedProject={{
          project_id: "agent-hub",
          permission_tier: "write",
          auto_exec_enabled: false,
          execution_start_hour: 0,
          execution_end_hour: 24,
          root_path: "/srv/workspaces/projects/agent-hub",
          updated_at: "2026-04-16T15:00:00Z",
          created_at: "2026-04-16T15:00:00Z",
        }}
        executionPermission={{
          allowed: false,
          permission_tier: "read",
          auto_exec_enabled: false,
          in_time_window: true,
          reason: "Execution permission denied",
        }}
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
              summary: "Waiting on permission",
              health: "ok",
              stalled: true,
              stall_reason: "Execution permission denied",
              current_tool_name: "bash",
              outstanding_tool_calls: 0,
              tool_calls_count: 0,
              files_touched: [],
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
          error: "Runtime blocked",
          stoppingSessionId: null,
          runtimeSyncKey: "sync-1",
          refresh: vi.fn(),
          stopSession: vi.fn(),
          stopCurrentStream: vi.fn(),
          stopActiveWork: vi.fn(),
        } as never}
        pulse={{ issue_groups: [{ summary: "Advisory warning" }] } as never}
        preview={{ memory_debug: { total_tokens: 9100 } } as never}
        previewLoading={false}
        onAskStatus={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText(/Hard blockers appear first/i)).toBeInTheDocument();
    expect(screen.getByText("Hard blocker")).toBeInTheDocument();
    expect(screen.getAllByText(/^Execution permission denied$/i)).toHaveLength(2);
    expect(screen.getByText(/Preview budget stays advisory/i)).toBeInTheDocument();
  });

  it("falls back to denied execution permission when runtime has no explicit blocker", () => {
    render(
      <PersonaBlockerPanel
        executionState="active"
        heartbeatIntervalMinutes={30}
        selectedProject={null}
        executionPermission={{
          allowed: false,
          permission_tier: "read",
          auto_exec_enabled: false,
          in_time_window: true,
          reason: "Execution permission denied",
        }}
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
              phase: "waiting_for_model",
              status: "active",
              summary: "Waiting on permission",
              health: "ok",
              stalled: false,
              stall_reason: null,
              current_tool_name: null,
              outstanding_tool_calls: 0,
              tool_calls_count: 0,
              files_touched: [],
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
          error: null,
          stoppingSessionId: null,
          runtimeSyncKey: "sync-1",
          refresh: vi.fn(),
          stopSession: vi.fn(),
          stopCurrentStream: vi.fn(),
          stopActiveWork: vi.fn(),
        } as never}
        pulse={{ issue_groups: [] } as never}
        preview={null}
        previewLoading={false}
        onAskStatus={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getAllByText(/^Execution permission denied$/i).length).toBeGreaterThanOrEqual(1);
  });
});
