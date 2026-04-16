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
        isTerminalThread
        sendMessage={sendMessage}
        cancelStream={vi.fn()}
        preferencesEndpoint="/api/preferences"
        onNewSession={vi.fn()}
      />,
    );

    expect(screen.getByText("Reply thread: agent-hub")).toBeInTheDocument();
    expect(screen.getByText("Next thread target: summitflow")).toBeInTheDocument();
    expect(screen.getByText("Reply continues this thread. New thread starts fresh on target.")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/Redirect Avery/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Status/i }));
    fireEvent.click(screen.getByRole("button", { name: /Plan/i }));
    fireEvent.click(screen.getByRole("button", { name: /Steer/i }));

    fireEvent.change(screen.getByPlaceholderText(/Redirect Avery/i), {
      target: { value: "Drop the polish pass and finish verification first." },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Redirect$/i }));

    expect(sendMessage).toHaveBeenNthCalledWith(
      1,
      "Pause and reply with concise status: current goal, blocker, lane owner, next move.",
    );
    expect(sendMessage).toHaveBeenNthCalledWith(
      2,
      "Revise the current plan. Keep what still holds. Show only the delta and rationale.",
    );
    expect(sendMessage).toHaveBeenNthCalledWith(
      3,
      "Redirect current work: Drop the polish pass and finish verification first.",
    );
  });
});
