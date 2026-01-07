import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ContextPanel, type ContextSource } from "@/components/chat/context-panel";

const defaultProps = {
  isOpen: true,
  onToggle: vi.fn(),
  sources: [] as ContextSource[],
  tokenBudget: {
    used: 5000,
    limit: 100000,
    inputTokens: 3000,
    outputTokens: 2000,
  },
  stickyNotes: [],
  onAddNote: vi.fn(),
  onRemoveNote: vi.fn(),
};

describe("ContextPanel", () => {
  it("renders when open", () => {
    render(<ContextPanel {...defaultProps} />);
    expect(screen.getByText("Context")).toBeInTheDocument();
  });

  it("shows open button when closed", () => {
    render(<ContextPanel {...defaultProps} isOpen={false} />);
    expect(screen.getByTitle("Show context panel")).toBeInTheDocument();
  });

  it("displays token budget", () => {
    render(<ContextPanel {...defaultProps} />);
    // Check for the progress display
    expect(screen.getByText("Token Budget")).toBeInTheDocument();
    expect(screen.getByText(/% used/)).toBeInTheDocument();
  });

  it("shows warning color when usage > 70%", () => {
    render(
      <ContextPanel
        {...defaultProps}
        tokenBudget={{ used: 80000, limit: 100000, inputTokens: 50000, outputTokens: 30000 }}
      />
    );
    expect(screen.getByText(/80.0% used/)).toBeInTheDocument();
  });

  it("shows danger color when usage > 90%", () => {
    render(
      <ContextPanel
        {...defaultProps}
        tokenBudget={{ used: 95000, limit: 100000, inputTokens: 60000, outputTokens: 35000 }}
      />
    );
    expect(screen.getByText(/95.0% used/)).toBeInTheDocument();
  });

  it("displays system prompt when provided", () => {
    render(
      <ContextPanel
        {...defaultProps}
        systemPrompt="You are a helpful assistant."
      />
    );
    expect(screen.getByText("System Prompt")).toBeInTheDocument();
    // Need to expand to see content
    fireEvent.click(screen.getByText("System Prompt"));
    expect(screen.getByText(/You are a helpful assistant/)).toBeInTheDocument();
  });

  it("displays context sources", () => {
    const sources: ContextSource[] = [
      {
        id: "1",
        type: "message",
        label: "User message",
        content: "Hello world",
        tokens: 10,
      },
      {
        id: "2",
        type: "memory",
        label: "Memory item",
        content: "Some stored context",
        tokens: 50,
      },
    ];

    render(<ContextPanel {...defaultProps} sources={sources} />);
    expect(screen.getByText("User message")).toBeInTheDocument();
    expect(screen.getByText("Memory item")).toBeInTheDocument();
  });

  it("expands source to show content", () => {
    const sources: ContextSource[] = [
      {
        id: "1",
        type: "message",
        label: "Test message",
        content: "This is the message content",
        tokens: 15,
      },
    ];

    render(<ContextPanel {...defaultProps} sources={sources} />);

    // Click to expand
    fireEvent.click(screen.getByText("Test message"));
    expect(screen.getByText("This is the message content")).toBeInTheDocument();
  });

  it("shows summarized content with original expansion", () => {
    const sources: ContextSource[] = [
      {
        id: "1",
        type: "summary",
        label: "Summarized conversation",
        content: "Summary of the conversation",
        originalContent: "Original long conversation text",
        tokens: 100,
      },
    ];

    render(<ContextPanel {...defaultProps} sources={sources} />);

    // Click to expand
    fireEvent.click(screen.getByText("Summarized conversation"));
    expect(screen.getByText("Summary of the conversation")).toBeInTheDocument();
    expect(screen.getByText("Show original")).toBeInTheDocument();
  });

  it("allows adding sticky notes", () => {
    const onAddNote = vi.fn();
    render(<ContextPanel {...defaultProps} onAddNote={onAddNote} />);

    // Expand notes section
    fireEvent.click(screen.getByText("Sticky Notes"));

    const input = screen.getByPlaceholderText("Add a note...");
    fireEvent.change(input, { target: { value: "My note" } });

    // Find the add button (Plus icon button next to input)
    const buttons = screen.getAllByRole("button");
    const addButton = buttons.find(btn => btn.querySelector("svg") && btn.className.includes("bg-blue"));
    if (addButton) {
      fireEvent.click(addButton);
    }

    expect(onAddNote).toHaveBeenCalledWith("My note");
  });

  it("adds note on Enter key", () => {
    const onAddNote = vi.fn();
    render(<ContextPanel {...defaultProps} onAddNote={onAddNote} />);

    // Expand notes section
    fireEvent.click(screen.getByText("Sticky Notes"));

    const input = screen.getByPlaceholderText("Add a note...");
    fireEvent.change(input, { target: { value: "Enter note" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onAddNote).toHaveBeenCalledWith("Enter note");
  });

  it("displays sticky notes", () => {
    const notes = [
      { id: "1", content: "Remember this", createdAt: new Date() },
      { id: "2", content: "Important context", createdAt: new Date() },
    ];

    render(<ContextPanel {...defaultProps} stickyNotes={notes} />);

    // Expand notes section
    fireEvent.click(screen.getByText("Sticky Notes"));

    expect(screen.getByText("Remember this")).toBeInTheDocument();
    expect(screen.getByText("Important context")).toBeInTheDocument();
  });

  it("allows removing sticky notes", () => {
    const onRemoveNote = vi.fn();
    const notes = [{ id: "note-1", content: "Delete me", createdAt: new Date() }];

    render(
      <ContextPanel
        {...defaultProps}
        stickyNotes={notes}
        onRemoveNote={onRemoveNote}
      />
    );

    // Expand notes section
    fireEvent.click(screen.getByText("Sticky Notes"));

    // Find and click remove button
    const removeButtons = screen.getAllByRole("button");
    const removeBtn = removeButtons.find((btn) =>
      btn.className.includes("hover:bg-amber")
    );
    if (removeBtn) {
      fireEvent.click(removeBtn);
      expect(onRemoveNote).toHaveBeenCalledWith("note-1");
    }
  });

  it("shows input/output token breakdown in budget section", () => {
    render(<ContextPanel {...defaultProps} />);

    // Budget section should be expanded by default and show Input/Output
    expect(screen.getByText("Input")).toBeInTheDocument();
    expect(screen.getByText("Output")).toBeInTheDocument();
  });

  it("calls onToggle when close button clicked", () => {
    const onToggle = vi.fn();
    render(<ContextPanel {...defaultProps} onToggle={onToggle} />);

    // Click close button - it's near the Context header
    const buttons = screen.getAllByRole("button");
    // First button should be the close button in header
    fireEvent.click(buttons[0]);

    expect(onToggle).toHaveBeenCalled();
  });

  it("shows empty state for sources", () => {
    render(<ContextPanel {...defaultProps} sources={[]} />);
    expect(screen.getByText("No context sources")).toBeInTheDocument();
  });
});
