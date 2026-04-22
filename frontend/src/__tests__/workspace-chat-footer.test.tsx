import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceChatFooter } from "@/app/persona/components/WorkspaceChatFooter";

vi.mock("@agent-hub/chat-ui", () => ({
  MessageInput: () => <div data-testid="message-input">composer</div>,
}));

describe("WorkspaceChatFooter", () => {
  it("shows stream status and jump-to-latest on one compact status row", () => {
    const onJumpToLatest = vi.fn();

    render(
      <WorkspaceChatFooter
        personaDisplayName="Avery"
        responseStatusLabel="Avery is responding"
        status="streaming"
        targetProjectId="summitflow"
        sessionProjectId="agent-hub"
        threadSessionId="sess-root"
        threadSource="session"
        isTerminalThread
        sendMessage={vi.fn()}
        cancelStream={vi.fn()}
        preferencesEndpoint="/api/preferences"
        onNewSession={vi.fn()}
        jumpToLatestLabel="2 new items · Jump to latest"
        onJumpToLatest={onJumpToLatest}
      />,
    );

    expect(screen.getByText("Avery is responding")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /2 new items · jump to latest/i }));
    expect(onJumpToLatest).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /new thread/i })).not.toBeInTheDocument();
    expect(screen.getByTestId("message-input")).toBeInTheDocument();
  });

  it("shows only the jump affordance when new activity arrives without a stream label", () => {
    render(
      <WorkspaceChatFooter
        personaDisplayName="Avery"
        responseStatusLabel={null}
        status="idle"
        targetProjectId="summitflow"
        sessionProjectId={null}
        threadSessionId="sess-draft"
        threadSource="draft"
        sendMessage={vi.fn()}
        cancelStream={vi.fn()}
        preferencesEndpoint="/api/preferences"
        onNewSession={vi.fn()}
        jumpToLatestLabel="Jump to latest"
        onJumpToLatest={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /jump to latest/i })).toBeInTheDocument();
    expect(screen.queryByText("draft · summitflow")).not.toBeInTheDocument();
  });

  it("stays focused on the composer when there is no status chrome to show", () => {
    render(
      <WorkspaceChatFooter
        personaDisplayName="Avery"
        responseStatusLabel={null}
        status="idle"
        targetProjectId="summitflow"
        sessionProjectId={null}
        sendMessage={vi.fn()}
        cancelStream={vi.fn()}
        preferencesEndpoint="/api/preferences"
        onNewSession={vi.fn()}
      />,
    );

    expect(screen.getByTestId("message-input")).toBeInTheDocument();
    expect(screen.queryByText("summitflow")).not.toBeInTheDocument();
  });
});
