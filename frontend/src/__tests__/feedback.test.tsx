import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { FeedbackButtons, FeedbackModal } from "@/components/feedback";

describe("FeedbackButtons", () => {
  it("renders thumbs up and thumbs down buttons", () => {
    render(<FeedbackButtons messageId="msg-1" />);

    expect(screen.getByTitle("Good response")).toBeInTheDocument();
    expect(screen.getByTitle("Poor response")).toBeInTheDocument();
  });

  it("calls onFeedback with positive when thumbs up clicked", () => {
    const onFeedback = vi.fn();
    render(<FeedbackButtons messageId="msg-1" onFeedback={onFeedback} />);

    fireEvent.click(screen.getByTitle("Good response"));

    expect(onFeedback).toHaveBeenCalledWith("msg-1", "positive");
  });

  it("calls onFeedback with negative when thumbs down clicked", () => {
    const onFeedback = vi.fn();
    render(<FeedbackButtons messageId="msg-1" onFeedback={onFeedback} />);

    fireEvent.click(screen.getByTitle("Poor response"));

    expect(onFeedback).toHaveBeenCalledWith("msg-1", "negative");
  });

  it("calls onNegativeFeedback when thumbs down clicked", () => {
    const onNegativeFeedback = vi.fn();
    render(<FeedbackButtons messageId="msg-1" onNegativeFeedback={onNegativeFeedback} />);

    fireEvent.click(screen.getByTitle("Poor response"));

    expect(onNegativeFeedback).toHaveBeenCalledWith("msg-1");
  });

  it("toggles feedback when clicking same button twice", () => {
    const onFeedback = vi.fn();
    render(<FeedbackButtons messageId="msg-1" onFeedback={onFeedback} />);

    // Click thumbs up
    fireEvent.click(screen.getByTitle("Good response"));
    expect(onFeedback).toHaveBeenCalledWith("msg-1", "positive");

    // Click thumbs up again to toggle off
    fireEvent.click(screen.getByTitle("Good response"));
    expect(onFeedback).toHaveBeenCalledWith("msg-1", null);
  });

  it("switches feedback when clicking different button", () => {
    const onFeedback = vi.fn();
    render(<FeedbackButtons messageId="msg-1" onFeedback={onFeedback} />);

    // Click thumbs up
    fireEvent.click(screen.getByTitle("Good response"));
    expect(onFeedback).toHaveBeenLastCalledWith("msg-1", "positive");

    // Click thumbs down
    fireEvent.click(screen.getByTitle("Poor response"));
    expect(onFeedback).toHaveBeenLastCalledWith("msg-1", "negative");
  });

  it("is disabled when disabled prop is true", () => {
    const onFeedback = vi.fn();
    render(<FeedbackButtons messageId="msg-1" onFeedback={onFeedback} disabled />);

    fireEvent.click(screen.getByTitle("Good response"));
    expect(onFeedback).not.toHaveBeenCalled();
  });

  it("shows initial feedback state", () => {
    render(<FeedbackButtons messageId="msg-1" initialFeedback="positive" />);

    const thumbsUp = screen.getByTitle("Good response");
    expect(thumbsUp).toHaveAttribute("aria-pressed", "true");
  });
});

describe("FeedbackModal", () => {
  const defaultProps = {
    isOpen: true,
    onClose: vi.fn(),
    onSubmit: vi.fn(),
    messageId: "msg-1",
    messagePreview: "This is a test message",
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders when open", () => {
    render(<FeedbackModal {...defaultProps} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("FEEDBACK.REPORT")).toBeInTheDocument();
  });

  it("does not render when closed", () => {
    render(<FeedbackModal {...defaultProps} isOpen={false} />);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows message preview", () => {
    render(<FeedbackModal {...defaultProps} />);

    expect(screen.getByText("This is a test message")).toBeInTheDocument();
  });

  it("shows category options", () => {
    render(<FeedbackModal {...defaultProps} />);

    expect(screen.getByText("Incorrect information")).toBeInTheDocument();
    expect(screen.getByText("Not helpful")).toBeInTheDocument();
    expect(screen.getByText("Incomplete response")).toBeInTheDocument();
    expect(screen.getByText("Inappropriate content")).toBeInTheDocument();
    expect(screen.getByText("Other issue")).toBeInTheDocument();
  });

  it("allows selecting a category", () => {
    render(<FeedbackModal {...defaultProps} />);

    const incorrectButton = screen.getByText("Incorrect information").closest("button");
    fireEvent.click(incorrectButton!);

    // Button should be visually selected (aria state or class change)
    expect(incorrectButton).toHaveClass("border-amber-400");
  });

  it("enables submit when category selected", () => {
    render(<FeedbackModal {...defaultProps} />);

    // Initially disabled
    const submitButton = screen.getByRole("button", { name: /submit feedback/i });
    expect(submitButton).toBeDisabled();

    // Select category
    fireEvent.click(screen.getByText("Incorrect information"));

    // Now enabled
    expect(submitButton).not.toBeDisabled();
  });

  it("calls onSubmit with feedback data", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<FeedbackModal {...defaultProps} onSubmit={onSubmit} />);

    // Select category
    fireEvent.click(screen.getByText("Not helpful"));

    // Add details
    const textarea = screen.getByPlaceholderText(/what went wrong/i);
    fireEvent.change(textarea, { target: { value: "The answer was vague" } });

    // Submit
    fireEvent.click(screen.getByRole("button", { name: /submit feedback/i }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith({
        messageId: "msg-1",
        category: "unhelpful",
        details: "The answer was vague",
      });
    });
  });

  it("calls onClose when close button clicked", () => {
    const onClose = vi.fn();
    render(<FeedbackModal {...defaultProps} onClose={onClose} />);

    fireEvent.click(screen.getByLabelText("Close modal"));

    expect(onClose).toHaveBeenCalled();
  });

  it("calls onClose when escape key pressed", () => {
    const onClose = vi.fn();
    render(<FeedbackModal {...defaultProps} onClose={onClose} />);

    // Press Escape key
    fireEvent.keyDown(document, { key: "Escape" });

    expect(onClose).toHaveBeenCalled();
  });

  it("shows success state after submission", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<FeedbackModal {...defaultProps} onSubmit={onSubmit} />);

    // Select and submit
    fireEvent.click(screen.getByText("Incorrect information"));
    fireEvent.click(screen.getByRole("button", { name: /submit feedback/i }));

    await waitFor(() => {
      expect(screen.getByText("Feedback received")).toBeInTheDocument();
    });
  });

  it("shows character count for details", () => {
    render(<FeedbackModal {...defaultProps} />);

    expect(screen.getByText("CHAR.COUNT: 0/500")).toBeInTheDocument();

    const textarea = screen.getByPlaceholderText(/what went wrong/i);
    fireEvent.change(textarea, { target: { value: "test" } });

    expect(screen.getByText("CHAR.COUNT: 4/500")).toBeInTheDocument();
  });
});
