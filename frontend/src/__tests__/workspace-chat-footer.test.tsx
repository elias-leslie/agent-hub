import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceChatFooter } from "@/app/persona/components/WorkspaceChatFooter";

vi.mock("@agent-hub/chat-ui", () => ({
  MessageInput: () => <div data-testid="message-input">composer</div>,
}));

describe("WorkspaceChatFooter", () => {
  it("keeps redirect drafts inspectable and labels persisted-thread provenance", () => {
    const sendMessage = vi.fn();

    render(
      <WorkspaceChatFooter
        personaDisplayName="Avery"
        responseStatusLabel={null}
        status="streaming"
        targetProjectId="summitflow"
        sessionProjectId="agent-hub"
        threadSessionId="sess-root"
        threadSource="session"
        isTerminalThread
        sendMessage={sendMessage}
        cancelStream={vi.fn()}
        preferencesEndpoint="/api/preferences"
        onNewSession={vi.fn()}
      />,
    );

    expect(screen.getByText("Session")).toBeInTheDocument();
    expect(screen.getByText("Reply thread project: agent-hub")).toBeInTheDocument();
    expect(screen.getByText("Next thread target: summitflow")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/Redirect session/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Steer/i }));

    expect(screen.getByText(/advisory redirect draft/i)).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Redirect session/i), {
      target: { value: "Drop the polish pass and finish verification first." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send advisory redirect/i }));

    expect(sendMessage).toHaveBeenCalledWith(
      "Advisory redirect for the persisted thread: Drop the polish pass and finish verification first.",
      undefined,
      "sess-root",
    );
  });

  it("uses draft provenance for a locked draft thread", () => {
    render(
      <WorkspaceChatFooter
        personaDisplayName="Avery"
        responseStatusLabel="Avery is responding"
        status="streaming"
        targetProjectId="summitflow"
        sessionProjectId={null}
        threadSessionId="sess-draft"
        threadSource="draft"
        sendMessage={vi.fn()}
        cancelStream={vi.fn()}
        preferencesEndpoint="/api/preferences"
        onNewSession={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Steer/i }));

    expect(screen.getAllByText("Draft").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/current draft thread/i).length).toBeGreaterThan(0);
    expect(screen.getByPlaceholderText(/Update draft thread/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Send draft update/i })).toBeInTheDocument();
  });

  it("uses steering language for a fresh thread before any session is locked", () => {
    const sendMessage = vi.fn();

    render(
      <WorkspaceChatFooter
        personaDisplayName="Avery"
        responseStatusLabel={null}
        status="idle"
        targetProjectId="summitflow"
        sessionProjectId={null}
        sendMessage={sendMessage}
        cancelStream={vi.fn()}
        preferencesEndpoint="/api/preferences"
        onNewSession={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Steer/i }));
    expect(screen.getByText(/advisory steering draft for the next thread/i)).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText(/Steer next thread/i), {
      target: { value: "Start with blocker review." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send steering draft/i }));

    expect(sendMessage).toHaveBeenCalledWith("Advisory steering for the next thread: Start with blocker review.");
  });
});
