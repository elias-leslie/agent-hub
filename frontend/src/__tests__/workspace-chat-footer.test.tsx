import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceChatFooter } from "@/app/persona/components/WorkspaceChatFooter";

vi.mock("@agent-hub/chat-ui", () => ({
  MessageInput: () => <div data-testid="message-input">composer</div>,
}));

describe("WorkspaceChatFooter", () => {
  it("keeps steer controls collapsed until requested and still sends redirect actions", () => {
    const sendMessage = vi.fn();

    render(
      <WorkspaceChatFooter
        personaDisplayName="Avery"
        responseStatusLabel={null}
        status="streaming"
        targetProjectId="summitflow"
        sessionProjectId="agent-hub"
        threadSessionId="sess-root"
        isTerminalThread
        sendMessage={sendMessage}
        cancelStream={vi.fn()}
        preferencesEndpoint="/api/preferences"
        onNewSession={vi.fn()}
      />,
    );

    expect(screen.getByText("Reply thread: agent-hub")).toBeInTheDocument();
    expect(screen.getByText("Next thread target: summitflow")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/Redirect Avery/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Plan/i }));
    fireEvent.click(screen.getByRole("button", { name: /Steer/i }));

    expect(
      screen.getByText(/sends a redirect instruction into the current thread/i),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Redirect Avery/i), {
      target: { value: "Drop the polish pass and finish verification first." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send redirect instruction/i }));

    expect(sendMessage).toHaveBeenNthCalledWith(
      1,
      "Revise the current plan. Keep what still holds. Show only the delta and rationale.",
    );
    expect(sendMessage).toHaveBeenNthCalledWith(
      2,
      "Redirect current work: Drop the polish pass and finish verification first.",
    );
  });

  it("uses redirect language for a locked draft thread even before the project metadata resolves", () => {
    render(
      <WorkspaceChatFooter
        personaDisplayName="Avery"
        responseStatusLabel="Avery is responding"
        status="streaming"
        targetProjectId="summitflow"
        sessionProjectId={null}
        threadSessionId="sess-draft"
        sendMessage={vi.fn()}
        cancelStream={vi.fn()}
        preferencesEndpoint="/api/preferences"
        onNewSession={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Steer/i }));

    expect(screen.getByText(/sends a redirect instruction into the current thread/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Redirect Avery/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Send redirect instruction/i })).toBeInTheDocument();
  });

  it("uses redirect language for an idle locked thread", () => {
    render(
      <WorkspaceChatFooter
        personaDisplayName="Avery"
        responseStatusLabel={null}
        status="idle"
        targetProjectId="summitflow"
        sessionProjectId="agent-hub"
        threadSessionId="sess-root"
        sendMessage={vi.fn()}
        cancelStream={vi.fn()}
        preferencesEndpoint="/api/preferences"
        onNewSession={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Steer/i }));

    expect(screen.getByText(/sends a redirect instruction into the current thread/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Redirect Avery/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Send redirect instruction/i })).toBeInTheDocument();
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
    expect(screen.getByText(/sends a steering instruction with the next message/i)).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText(/Steer Avery/i), {
      target: { value: "Start with blocker review." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send steering instruction/i }));

    expect(sendMessage).toHaveBeenCalledWith("Steering instruction for next thread: Start with blocker review.");
  });
});
