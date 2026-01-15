import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import {
  ToolApprovalModal,
  ApprovalQueue,
  ApprovalBadge,
  RiskIndicator,
  type ApprovalRequest,
} from "@/components/tool-approval";

// Test fixtures
const lowRiskRequest: ApprovalRequest = {
  id: "req-1",
  toolCall: {
    id: "tool-1",
    toolName: "read_file",
    parameters: { path: "/tmp/test.txt" },
    riskLevel: "low",
    timestamp: new Date(),
  },
  timeoutSeconds: 30,
  agentName: "Claude Sonnet",
};

const mediumRiskRequest: ApprovalRequest = {
  id: "req-2",
  toolCall: {
    id: "tool-2",
    toolName: "write_file",
    parameters: { path: "/tmp/output.txt", content: "Hello" },
    riskLevel: "medium",
    timestamp: new Date(),
  },
  timeoutSeconds: 30,
  agentName: "Claude Sonnet",
};

const highRiskRequest: ApprovalRequest = {
  id: "req-3",
  toolCall: {
    id: "tool-3",
    toolName: "execute_command",
    parameters: { command: "rm -rf /tmp/test" },
    riskLevel: "high",
    timestamp: new Date(),
  },
  timeoutSeconds: 30,
  agentName: "Claude Opus",
};

describe("ToolApprovalModal", () => {
  const onDecision = vi.fn();
  const _onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders tool name and parameters", () => {
    render(
      <ToolApprovalModal request={lowRiskRequest} onDecision={onDecision} />,
    );
    // Tool name appears in header and remember checkbox - check both exist
    const toolNameElements = screen.getAllByText("read_file");
    expect(toolNameElements.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/\/tmp\/test.txt/)).toBeInTheDocument();
  });

  it("displays agent name when provided", () => {
    render(
      <ToolApprovalModal request={lowRiskRequest} onDecision={onDecision} />,
    );
    expect(screen.getByText("Claude Sonnet")).toBeInTheDocument();
  });

  it("shows low risk styling for low risk tools", () => {
    render(
      <ToolApprovalModal request={lowRiskRequest} onDecision={onDecision} />,
    );
    expect(
      screen.getByText("Safe operation with minimal impact"),
    ).toBeInTheDocument();
  });

  it("shows medium risk styling for medium risk tools", () => {
    render(
      <ToolApprovalModal request={mediumRiskRequest} onDecision={onDecision} />,
    );
    expect(
      screen.getByText("Review parameters before approving"),
    ).toBeInTheDocument();
  });

  it("shows high risk styling for high risk tools", () => {
    render(
      <ToolApprovalModal request={highRiskRequest} onDecision={onDecision} />,
    );
    expect(
      screen.getByText("Potentially destructive - review carefully"),
    ).toBeInTheDocument();
  });

  it("displays timeout countdown", () => {
    render(
      <ToolApprovalModal request={lowRiskRequest} onDecision={onDecision} />,
    );
    expect(screen.getByText("30s")).toBeInTheDocument();
  });

  it("calls onDecision with approve when Approve clicked", () => {
    render(
      <ToolApprovalModal request={lowRiskRequest} onDecision={onDecision} />,
    );
    fireEvent.click(screen.getByText("Approve"));
    expect(onDecision).toHaveBeenCalledWith("approve", false);
  });

  it("calls onDecision with deny when Deny clicked", () => {
    render(
      <ToolApprovalModal request={lowRiskRequest} onDecision={onDecision} />,
    );
    fireEvent.click(screen.getByText("Deny"));
    expect(onDecision).toHaveBeenCalledWith("deny", false);
  });

  it("calls onDecision with approve_all when YOLO clicked", () => {
    render(
      <ToolApprovalModal request={lowRiskRequest} onDecision={onDecision} />,
    );
    fireEvent.click(screen.getByText("Approve All (YOLO)"));
    expect(onDecision).toHaveBeenCalledWith("approve_all", false);
  });

  it("calls onDecision with deny_all when Deny All clicked", () => {
    render(
      <ToolApprovalModal request={lowRiskRequest} onDecision={onDecision} />,
    );
    fireEvent.click(screen.getByText("Deny All"));
    expect(onDecision).toHaveBeenCalledWith("deny_all", false);
  });

  it("passes rememberChoice when checkbox is checked", () => {
    render(
      <ToolApprovalModal request={lowRiskRequest} onDecision={onDecision} />,
    );

    // Check the remember choice checkbox
    const checkbox = screen.getByRole("checkbox");
    fireEvent.click(checkbox);

    // Click approve
    fireEvent.click(screen.getByText("Approve"));
    expect(onDecision).toHaveBeenCalledWith("approve", true);
  });

  it("shows queue count when queueLength > 0", () => {
    render(
      <ToolApprovalModal
        request={lowRiskRequest}
        onDecision={onDecision}
        queueLength={3}
      />,
    );
    expect(screen.getByText("+3 more")).toBeInTheDocument();
  });

  it("toggles parameter expansion", () => {
    render(
      <ToolApprovalModal request={lowRiskRequest} onDecision={onDecision} />,
    );

    // Click to expand
    fireEvent.click(screen.getByText("Expand"));
    expect(screen.getByText("Collapse")).toBeInTheDocument();
  });

  it("calls onDecision with timeout when timer expires", () => {
    render(
      <ToolApprovalModal
        request={{ ...lowRiskRequest, timeoutSeconds: 1 }}
        onDecision={onDecision}
      />,
    );

    // Fast-forward past timeout
    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(onDecision).toHaveBeenCalledWith("timeout", false);
  });

  it("responds to Y keyboard shortcut", () => {
    render(
      <ToolApprovalModal request={lowRiskRequest} onDecision={onDecision} />,
    );

    fireEvent.keyDown(window, { key: "y" });
    expect(onDecision).toHaveBeenCalledWith("approve", false);
  });

  it("responds to N keyboard shortcut", () => {
    render(
      <ToolApprovalModal request={lowRiskRequest} onDecision={onDecision} />,
    );

    fireEvent.keyDown(window, { key: "n" });
    expect(onDecision).toHaveBeenCalledWith("deny", false);
  });

  it("responds to Shift+A keyboard shortcut for approve all", () => {
    render(
      <ToolApprovalModal request={lowRiskRequest} onDecision={onDecision} />,
    );

    fireEvent.keyDown(window, { key: "a", shiftKey: true });
    expect(onDecision).toHaveBeenCalledWith("approve_all", false);
  });
});

describe("ApprovalQueue", () => {
  const onSelect = vi.fn();
  const requests = [lowRiskRequest, mediumRiskRequest, highRiskRequest];

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing when queue is empty", () => {
    const { container } = render(
      <ApprovalQueue requests={[]} onSelect={onSelect} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders pending approvals count", () => {
    render(<ApprovalQueue requests={requests} onSelect={onSelect} />);
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("Pending Approvals")).toBeInTheDocument();
  });

  it("sorts requests by risk level (high first)", () => {
    render(<ApprovalQueue requests={requests} onSelect={onSelect} />);

    const toolNames = screen.getAllByText(
      /read_file|write_file|execute_command/,
    );
    // High risk should be first
    expect(toolNames[0]).toHaveTextContent("execute_command");
  });

  it("shows tool name for each request", () => {
    render(<ApprovalQueue requests={requests} onSelect={onSelect} />);
    expect(screen.getByText("read_file")).toBeInTheDocument();
    expect(screen.getByText("write_file")).toBeInTheDocument();
    expect(screen.getByText("execute_command")).toBeInTheDocument();
  });

  it("calls onSelect when item clicked", () => {
    render(<ApprovalQueue requests={requests} onSelect={onSelect} />);
    fireEvent.click(screen.getByText("read_file"));
    expect(onSelect).toHaveBeenCalledWith(lowRiskRequest);
  });

  it("shows agent name for each request", () => {
    render(<ApprovalQueue requests={requests} onSelect={onSelect} />);
    expect(screen.getAllByText("Claude Sonnet").length).toBe(2);
    expect(screen.getByText("Claude Opus")).toBeInTheDocument();
  });
});

describe("ApprovalBadge", () => {
  const onClick = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing when count is 0", () => {
    const { container } = render(<ApprovalBadge count={0} onClick={onClick} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows pending count", () => {
    render(<ApprovalBadge count={5} onClick={onClick} />);
    expect(screen.getByText("5 pending")).toBeInTheDocument();
  });

  it("applies high risk styling when hasHighRisk", () => {
    const { container } = render(
      <ApprovalBadge count={3} hasHighRisk onClick={onClick} />,
    );
    expect(container.firstChild).toHaveClass("bg-rose-100");
  });

  it("shows pulsing indicator for high risk", () => {
    const { container } = render(
      <ApprovalBadge count={3} hasHighRisk onClick={onClick} />,
    );
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("calls onClick when clicked", () => {
    render(<ApprovalBadge count={3} onClick={onClick} />);
    fireEvent.click(screen.getByText("3 pending"));
    expect(onClick).toHaveBeenCalled();
  });
});

describe("RiskIndicator", () => {
  it("renders low risk indicator", () => {
    render(<RiskIndicator level="low" />);
    expect(screen.getByText("Low")).toBeInTheDocument();
  });

  it("renders medium risk indicator", () => {
    render(<RiskIndicator level="medium" />);
    expect(screen.getByText("Medium")).toBeInTheDocument();
  });

  it("renders high risk indicator", () => {
    render(<RiskIndicator level="high" />);
    expect(screen.getByText("High")).toBeInTheDocument();
  });

  it("hides label when showLabel is false", () => {
    render(<RiskIndicator level="high" showLabel={false} />);
    expect(screen.queryByText("High")).not.toBeInTheDocument();
  });

  it("applies size classes correctly", () => {
    const { rerender } = render(<RiskIndicator level="low" size="sm" />);
    expect(screen.getByText("Low").parentElement).toHaveClass("text-xs");

    rerender(<RiskIndicator level="low" size="lg" />);
    expect(screen.getByText("Low").parentElement).toHaveClass("text-base");
  });

  it("applies correct color for each risk level", () => {
    const { rerender } = render(<RiskIndicator level="low" />);
    expect(screen.getByText("Low").parentElement).toHaveClass("bg-emerald-100");

    rerender(<RiskIndicator level="medium" />);
    expect(screen.getByText("Medium").parentElement).toHaveClass(
      "bg-amber-100",
    );

    rerender(<RiskIndicator level="high" />);
    expect(screen.getByText("High").parentElement).toHaveClass("bg-rose-100");
  });
});
