import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  ActivityIndicator,
  ActivityIndicatorInline,
} from "@/components/chat/activity-indicator";

describe("ActivityIndicator", () => {
  it("renders idle state", () => {
    render(<ActivityIndicator state="idle" />);
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("renders connecting state", () => {
    render(<ActivityIndicator state="connecting" />);
    expect(screen.getByText("Connecting...")).toBeInTheDocument();
  });

  it("renders thinking state", () => {
    render(<ActivityIndicator state="thinking" />);
    expect(screen.getByText("Thinking...")).toBeInTheDocument();
  });

  it("renders streaming state", () => {
    render(<ActivityIndicator state="streaming" />);
    expect(screen.getByText("Responding...")).toBeInTheDocument();
  });

  it("renders error state", () => {
    render(<ActivityIndicator state="error" />);
    expect(screen.getByText("Error")).toBeInTheDocument();
  });

  it("renders cancelling state", () => {
    render(<ActivityIndicator state="cancelling" />);
    expect(screen.getByText("Cancelling...")).toBeInTheDocument();
  });

  it("shows tool name when calling_tool", () => {
    render(
      <ActivityIndicator
        state="calling_tool"
        toolCall={{ name: "search_web", status: "running" }}
      />
    );
    expect(screen.getByText("Calling search_web...")).toBeInTheDocument();
    expect(screen.getByText("search_web")).toBeInTheDocument();
  });

  it("shows step progress when provided", () => {
    render(
      <ActivityIndicator
        state="streaming"
        stepProgress={{ current: 2, total: 5 }}
      />
    );
    expect(screen.getByText(/2\/5/)).toBeInTheDocument();
  });

  it("shows expandable thinking content", () => {
    render(
      <ActivityIndicator
        state="thinking"
        thinkingContent={{
          content: "Let me think about this...",
          timestamp: new Date(),
        }}
      />
    );

    // Thinking panel should be visible
    expect(screen.getByText("Extended Thinking")).toBeInTheDocument();

    // Content hidden by default
    expect(screen.queryByText("Let me think about this...")).not.toBeInTheDocument();

    // Click to expand
    fireEvent.click(screen.getByText("Extended Thinking"));
    expect(screen.getByText("Let me think about this...")).toBeInTheDocument();
  });

  it("shows complete status for tool call", () => {
    render(
      <ActivityIndicator
        state="calling_tool"
        toolCall={{ name: "read_file", status: "complete" }}
      />
    );
    expect(screen.getByText("read_file")).toBeInTheDocument();
    // Check for checkmark icon presence (complete status)
  });

  it("shows error status for tool call", () => {
    render(
      <ActivityIndicator
        state="calling_tool"
        toolCall={{ name: "write_file", status: "error" }}
      />
    );
    expect(screen.getByText("write_file")).toBeInTheDocument();
  });
});

describe("ActivityIndicatorInline", () => {
  it("renders inline idle state", () => {
    render(<ActivityIndicatorInline state="idle" />);
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("renders inline streaming state", () => {
    render(<ActivityIndicatorInline state="streaming" />);
    expect(screen.getByText("Responding...")).toBeInTheDocument();
  });

  it("applies custom className", () => {
    const { container } = render(
      <ActivityIndicatorInline state="idle" className="custom-class" />
    );
    expect(container.firstChild).toHaveClass("custom-class");
  });
});
