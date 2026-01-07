import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MessageList } from "@/components/chat/message-list";
import type { ChatMessage } from "@/types/chat";

const createMessage = (overrides: Partial<ChatMessage> = {}): ChatMessage => ({
  id: "msg-1",
  role: "user",
  content: "Hello",
  timestamp: new Date(),
  ...overrides,
});

describe("MessageList - Edit and Regenerate", () => {
  it("renders messages correctly", () => {
    const messages: ChatMessage[] = [
      createMessage({ id: "1", content: "User message" }),
      createMessage({ id: "2", role: "assistant", content: "Assistant message" }),
    ];

    render(<MessageList messages={messages} isStreaming={false} />);

    expect(screen.getByText("User message")).toBeInTheDocument();
    expect(screen.getByText("Assistant message")).toBeInTheDocument();
  });

  it("shows empty state when no messages", () => {
    render(<MessageList messages={[]} isStreaming={false} />);
    expect(screen.getByText("Start a conversation")).toBeInTheDocument();
  });

  it("shows edit button on hover for user messages when callback provided", async () => {
    const onEdit = vi.fn();
    const messages = [createMessage({ content: "Edit me" })];

    render(
      <MessageList
        messages={messages}
        isStreaming={false}
        onEditMessage={onEdit}
      />
    );

    // Edit button should exist (though hidden until hover)
    expect(screen.getByTitle("Edit message")).toBeInTheDocument();
  });

  it("shows regenerate button on hover for assistant messages when callback provided", () => {
    const onRegenerate = vi.fn();
    const messages = [
      createMessage({ id: "1", content: "User" }),
      createMessage({ id: "2", role: "assistant", content: "Assistant" }),
    ];

    render(
      <MessageList
        messages={messages}
        isStreaming={false}
        onRegenerateMessage={onRegenerate}
      />
    );

    expect(screen.getByTitle("Regenerate response")).toBeInTheDocument();
  });

  it("enters edit mode when edit button clicked", () => {
    const onEdit = vi.fn();
    const messages = [createMessage({ content: "Original content" })];

    render(
      <MessageList
        messages={messages}
        isStreaming={false}
        onEditMessage={onEdit}
      />
    );

    fireEvent.click(screen.getByTitle("Edit message"));

    // Should show textarea with original content
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toHaveValue("Original content");
  });

  it("calls onEdit with new content when saved", () => {
    const onEdit = vi.fn();
    const messages = [createMessage({ id: "msg-1", content: "Original" })];

    render(
      <MessageList
        messages={messages}
        isStreaming={false}
        onEditMessage={onEdit}
      />
    );

    fireEvent.click(screen.getByTitle("Edit message"));

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "Edited content" } });

    // Find save button (second button in edit controls, after cancel)
    const buttons = screen.getAllByRole("button");
    // In edit mode: cancel (X) is first, save (Check) is second
    fireEvent.click(buttons[1]);

    expect(onEdit).toHaveBeenCalledWith("msg-1", "Edited content");
  });

  it("cancels edit without calling onEdit", () => {
    const onEdit = vi.fn();
    const messages = [createMessage({ content: "Original" })];

    render(
      <MessageList
        messages={messages}
        isStreaming={false}
        onEditMessage={onEdit}
      />
    );

    fireEvent.click(screen.getByTitle("Edit message"));

    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "Changed" } });

    // Cancel - find X button (second button in edit mode)
    const buttons = screen.getAllByRole("button");
    // Click first button in the edit controls (cancel)
    fireEvent.click(buttons[0]);

    expect(onEdit).not.toHaveBeenCalled();
  });

  it("calls onRegenerate when regenerate button clicked", () => {
    const onRegenerate = vi.fn();
    const messages = [
      createMessage({ id: "1", content: "User" }),
      createMessage({ id: "2", role: "assistant", content: "Assistant" }),
    ];

    render(
      <MessageList
        messages={messages}
        isStreaming={false}
        onRegenerateMessage={onRegenerate}
      />
    );

    fireEvent.click(screen.getByTitle("Regenerate response"));

    expect(onRegenerate).toHaveBeenCalledWith("2");
  });

  it("shows edited indicator for edited messages", () => {
    const messages = [
      createMessage({
        content: "Edited content",
        edited: true,
        editedAt: new Date(),
      }),
    ];

    render(<MessageList messages={messages} isStreaming={false} />);

    expect(screen.getByText("edited")).toBeInTheDocument();
  });

  it("shows version history when available and clicked", () => {
    const messages = [
      createMessage({
        content: "Current version",
        edited: true,
        previousVersions: ["First version", "Second version"],
      }),
    ];

    render(<MessageList messages={messages} isStreaming={false} />);

    // History button should be visible
    const historyButton = screen.getByRole("button");
    fireEvent.click(historyButton);

    expect(screen.getByText("Previous versions:")).toBeInTheDocument();
    expect(screen.getByText("First version")).toBeInTheDocument();
    expect(screen.getByText("Second version")).toBeInTheDocument();
  });

  it("hides action buttons during streaming", () => {
    const onEdit = vi.fn();
    const messages = [createMessage({ content: "User message" })];

    render(
      <MessageList
        messages={messages}
        isStreaming={true}
        onEditMessage={onEdit}
      />
    );

    expect(screen.queryByTitle("Edit message")).not.toBeInTheDocument();
  });

  it("does not show edit button for assistant messages", () => {
    const onEdit = vi.fn();
    const messages = [
      createMessage({ role: "assistant", content: "Assistant response" }),
    ];

    render(
      <MessageList
        messages={messages}
        isStreaming={false}
        onEditMessage={onEdit}
      />
    );

    expect(screen.queryByTitle("Edit message")).not.toBeInTheDocument();
  });

  it("does not show regenerate button for user messages", () => {
    const onRegenerate = vi.fn();
    const messages = [createMessage({ content: "User message" })];

    render(
      <MessageList
        messages={messages}
        isStreaming={false}
        onRegenerateMessage={onRegenerate}
      />
    );

    expect(screen.queryByTitle("Regenerate response")).not.toBeInTheDocument();
  });
});
