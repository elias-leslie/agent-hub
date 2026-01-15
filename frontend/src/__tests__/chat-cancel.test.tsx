/**
 * Tests for chat cancellation UI.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MessageInput } from "@/components/chat/message-input";
import { MessageList } from "@/components/chat/message-list";
import type { ChatMessage } from "@/types/chat";

describe("MessageInput", () => {
  const mockOnSend = vi.fn();
  const mockOnCancel = vi.fn();

  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("shows Send button when idle", () => {
    render(
      <MessageInput
        onSend={mockOnSend}
        onCancel={mockOnCancel}
        status="idle"
      />,
    );

    expect(screen.getByLabelText("Send message")).toBeInTheDocument();
    expect(screen.queryByLabelText("Stop generating")).not.toBeInTheDocument();
  });

  it("shows Stop button when streaming", () => {
    render(
      <MessageInput
        onSend={mockOnSend}
        onCancel={mockOnCancel}
        status="streaming"
      />,
    );

    expect(screen.getByLabelText("Stop generating")).toBeInTheDocument();
    expect(screen.queryByLabelText("Send message")).not.toBeInTheDocument();
  });

  it("shows Stop button when cancelling", () => {
    render(
      <MessageInput
        onSend={mockOnSend}
        onCancel={mockOnCancel}
        status="cancelling"
      />,
    );

    expect(screen.getByLabelText("Stop generating")).toBeInTheDocument();
  });

  it("calls onCancel when Stop button is clicked", () => {
    render(
      <MessageInput
        onSend={mockOnSend}
        onCancel={mockOnCancel}
        status="streaming"
      />,
    );

    fireEvent.click(screen.getByLabelText("Stop generating"));
    expect(mockOnCancel).toHaveBeenCalledTimes(1);
  });

  it("disables Stop button when cancelling", () => {
    render(
      <MessageInput
        onSend={mockOnSend}
        onCancel={mockOnCancel}
        status="cancelling"
      />,
    );

    const stopButton = screen.getByLabelText("Stop generating");
    expect(stopButton).toBeDisabled();
  });

  it("disables textarea when streaming", () => {
    render(
      <MessageInput
        onSend={mockOnSend}
        onCancel={mockOnCancel}
        status="streaming"
      />,
    );

    const textarea = screen.getByPlaceholderText("Waiting for response...");
    expect(textarea).toBeDisabled();
  });
});

describe("MessageList", () => {
  it("shows cancelled indicator on cancelled messages", () => {
    const messages: ChatMessage[] = [
      {
        id: "1",
        role: "user",
        content: "Hello",
        timestamp: new Date(),
      },
      {
        id: "2",
        role: "assistant",
        content: "Hi there! I was just starting to explain—",
        timestamp: new Date(),
        cancelled: true,
        inputTokens: 10,
        outputTokens: 15,
      },
    ];

    render(<MessageList messages={messages} isStreaming={false} />);

    expect(screen.getByText("[cancelled]")).toBeInTheDocument();
  });

  it("shows token counts on completed messages", () => {
    const messages: ChatMessage[] = [
      {
        id: "1",
        role: "assistant",
        content: "Hello!",
        timestamp: new Date(),
        inputTokens: 100,
        outputTokens: 50,
      },
    ];

    render(<MessageList messages={messages} isStreaming={false} />);

    expect(screen.getByText(/In: 100/)).toBeInTheDocument();
    expect(screen.getByText(/Out: 50/)).toBeInTheDocument();
  });

  it("shows empty state when no messages", () => {
    render(<MessageList messages={[]} isStreaming={false} />);

    expect(screen.getByText("Start a conversation")).toBeInTheDocument();
  });
});
