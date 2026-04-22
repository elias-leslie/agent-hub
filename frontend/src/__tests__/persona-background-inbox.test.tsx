import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PersonaBackgroundInbox } from "@/app/persona/components/PersonaBackgroundInbox";

describe("PersonaBackgroundInbox", () => {
  it("opens inspectable advisory drafts before sending lane actions", () => {
    const onHandoffSession = vi.fn();

    render(
      <PersonaBackgroundInbox
        entries={[]}
        activeChildSessions={[
          {
            id: "lane-1",
            project_id: "agent-hub",
            provider: "codex",
            model: "gpt-5.4",
            status: "active",
            agent_slug: "coder",
            session_type: "completion",
            parent_session_id: "root-1",
            external_id: null,
            current_branch: null,
            live_activity: {
              phase: "waiting_for_model",
              status: "active",
              summary: "Fixing command deck labels",
              health: "ok",
              stalled: false,
              outstanding_tool_calls: 0,
              tool_calls_count: 1,
              files_touched: [],
            },
            message_count: 0,
            total_input_tokens: 0,
            total_output_tokens: 0,
            created_at: "2026-04-16T12:00:00Z",
            updated_at: "2026-04-16T12:01:00Z",
          },
        ] as never[]}
        activeSessionId={null}
        stoppingSessionId={null}
        onSelectSession={vi.fn()}
        onStopSession={vi.fn()}
        onRedirectSession={vi.fn()}
        onPromoteSession={vi.fn()}
        onHandoffSession={onHandoffSession}
      />,
    );

    expect(screen.getByText(/redirect, promote, and handoff open drafts first/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Open handoff draft/i }));

    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByText("Advisory")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Inspect advisory handoff draft/i), {
      target: { value: "Advisory handoff: keep verification scope narrow." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send advisory handoff/i }));

    expect(onHandoffSession).toHaveBeenCalledWith("lane-1", "Advisory handoff: keep verification scope narrow.");
  });
});
