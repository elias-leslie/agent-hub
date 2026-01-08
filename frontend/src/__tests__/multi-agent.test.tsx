import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  AgentBadge,
  AgentAvatar,
  AgentSelector,
  TurnIndicator,
  TurnIndicatorCompact,
  AgentMessageBubble,
  AgentExchange,
  DeliberationPanel,
  type Agent,
  type AgentTurnState,
  type AgentMessage,
  type AgentExchangeThread,
} from "@/components/chat/multi-agent";

// Test agents
const claudeAgent: Agent = {
  id: "claude-sonnet",
  name: "Claude Sonnet 4.5",
  shortName: "Sonnet 4.5",
  provider: "claude",
  model: "claude-sonnet-4-5-20250514",
};

const geminiAgent: Agent = {
  id: "gemini-flash",
  name: "Gemini 3 Flash",
  shortName: "Flash",
  provider: "gemini",
  model: "gemini-3-flash-preview",
};

const testAgents = [claudeAgent, geminiAgent];

describe("AgentBadge", () => {
  it("renders Claude agent with orange styling", () => {
    render(<AgentBadge agent={claudeAgent} />);
    expect(screen.getByText("Sonnet 4.5")).toBeInTheDocument();
  });

  it("renders Gemini agent with blue styling", () => {
    render(<AgentBadge agent={geminiAgent} />);
    expect(screen.getByText("Flash")).toBeInTheDocument();
  });

  it("shows model identifier when showModel is true", () => {
    render(<AgentBadge agent={claudeAgent} showModel />);
    expect(screen.getByText("Sonnet 4.5")).toBeInTheDocument();
    // Model suffix should appear
    expect(screen.getByText("20250514")).toBeInTheDocument();
  });

  it("applies size classes correctly", () => {
    const { rerender } = render(<AgentBadge agent={claudeAgent} size="sm" />);
    expect(screen.getByText("Sonnet 4.5").parentElement).toHaveClass("text-xs");

    rerender(<AgentBadge agent={claudeAgent} size="lg" />);
    expect(screen.getByText("Sonnet 4.5").parentElement).toHaveClass("text-base");
  });
});

describe("AgentAvatar", () => {
  it("renders Claude avatar", () => {
    render(<AgentAvatar agent={claudeAgent} />);
    // Should render without error
    expect(document.querySelector("svg")).toBeInTheDocument();
  });

  it("shows active indicator when isActive", () => {
    const { container } = render(<AgentAvatar agent={claudeAgent} isActive />);
    // Active indicator has animate-pulse class
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("applies ring styling when active", () => {
    const { container } = render(<AgentAvatar agent={claudeAgent} isActive />);
    expect(container.firstChild).toHaveClass("ring-2");
  });
});

describe("AgentSelector", () => {
  const onSelect = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders with 'All Agents' selected by default", () => {
    render(
      <AgentSelector
        agents={testAgents}
        selectedAgent="all"
        onSelect={onSelect}
      />
    );
    expect(screen.getByText("All Agents")).toBeInTheDocument();
  });

  it("shows dropdown when clicked", () => {
    render(
      <AgentSelector
        agents={testAgents}
        selectedAgent="all"
        onSelect={onSelect}
      />
    );

    fireEvent.click(screen.getByText("All Agents"));

    // Should show all agents in dropdown
    expect(screen.getByText("Sonnet 4.5")).toBeInTheDocument();
    expect(screen.getByText("Flash")).toBeInTheDocument();
  });

  it("calls onSelect when agent is selected", () => {
    render(
      <AgentSelector
        agents={testAgents}
        selectedAgent="all"
        onSelect={onSelect}
      />
    );

    fireEvent.click(screen.getByText("All Agents"));
    fireEvent.click(screen.getByText("Sonnet 4.5"));

    expect(onSelect).toHaveBeenCalledWith(claudeAgent);
  });

  it("shows selected agent when not 'all'", () => {
    render(
      <AgentSelector
        agents={testAgents}
        selectedAgent={claudeAgent}
        onSelect={onSelect}
      />
    );
    expect(screen.getByText("Sonnet 4.5")).toBeInTheDocument();
  });

  it("is disabled when disabled prop is true", () => {
    render(
      <AgentSelector
        agents={testAgents}
        selectedAgent="all"
        onSelect={onSelect}
        disabled
      />
    );

    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
  });
});

describe("TurnIndicator", () => {
  it("renders nothing when no agents are active", () => {
    const turnStates: AgentTurnState[] = [
      { agentId: "claude-sonnet", state: "idle" },
    ];

    const { container } = render(
      <TurnIndicator agents={testAgents} turnStates={turnStates} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows active agent when thinking", () => {
    const turnStates: AgentTurnState[] = [
      { agentId: "claude-sonnet", state: "thinking", startedAt: new Date() },
    ];

    render(<TurnIndicator agents={testAgents} turnStates={turnStates} />);
    expect(screen.getByText("Sonnet 4.5")).toBeInTheDocument();
    expect(screen.getByText("thinking...")).toBeInTheDocument();
  });

  it("shows multiple active agents", () => {
    const turnStates: AgentTurnState[] = [
      { agentId: "claude-sonnet", state: "responding", startedAt: new Date() },
      { agentId: "gemini-flash", state: "waiting", startedAt: new Date() },
    ];

    render(<TurnIndicator agents={testAgents} turnStates={turnStates} />);
    expect(screen.getByText("Sonnet 4.5")).toBeInTheDocument();
    expect(screen.getByText("Flash")).toBeInTheDocument();
  });
});

describe("TurnIndicatorCompact", () => {
  it("renders nothing when idle", () => {
    const { container } = render(
      <TurnIndicatorCompact agent={claudeAgent} state="idle" />
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows agent and state when active", () => {
    render(<TurnIndicatorCompact agent={claudeAgent} state="thinking" />);
    expect(screen.getByText("Sonnet 4.5")).toBeInTheDocument();
    expect(screen.getByText("thinking...")).toBeInTheDocument();
  });
});

describe("AgentMessageBubble", () => {
  const testMessage: AgentMessage = {
    id: "msg-1",
    agentId: "claude-sonnet",
    content: "Hello, I am Claude.",
    timestamp: new Date(),
  };

  it("renders message content", () => {
    render(<AgentMessageBubble agent={claudeAgent} message={testMessage} />);
    expect(screen.getByText("Hello, I am Claude.")).toBeInTheDocument();
  });

  it("shows agent badge", () => {
    render(<AgentMessageBubble agent={claudeAgent} message={testMessage} />);
    expect(screen.getByText("Sonnet 4.5")).toBeInTheDocument();
  });

  it("shows streaming indicator when isStreaming", () => {
    const { container } = render(
      <AgentMessageBubble agent={claudeAgent} message={testMessage} isStreaming />
    );
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
  });

  it("shows deliberation badge for deliberation messages", () => {
    const deliberationMsg: AgentMessage = {
      ...testMessage,
      isDeliberation: true,
    };
    render(<AgentMessageBubble agent={claudeAgent} message={deliberationMsg} />);
    expect(screen.getByText("deliberation")).toBeInTheDocument();
  });

  it("shows consensus badge for consensus messages", () => {
    const consensusMsg: AgentMessage = {
      ...testMessage,
      isConsensus: true,
    };
    render(<AgentMessageBubble agent={claudeAgent} message={consensusMsg} />);
    expect(screen.getByText("consensus")).toBeInTheDocument();
  });
});

describe("AgentExchange", () => {
  const exchangeMessage: AgentMessage = {
    id: "msg-exchange",
    agentId: "claude-sonnet",
    content: "I agree with your assessment.",
    timestamp: new Date(),
    replyToAgentId: "gemini-flash",
  };

  it("renders from and to agents", () => {
    render(
      <AgentExchange
        fromAgent={claudeAgent}
        toAgent={geminiAgent}
        message={exchangeMessage}
      />
    );
    expect(screen.getByText(/Sonnet 4.5 to Flash/)).toBeInTheDocument();
  });

  it("renders message content", () => {
    render(
      <AgentExchange
        fromAgent={claudeAgent}
        toAgent={geminiAgent}
        message={exchangeMessage}
      />
    );
    expect(screen.getByText("I agree with your assessment.")).toBeInTheDocument();
  });
});

describe("DeliberationPanel", () => {
  const deliberationMessages: AgentMessage[] = [
    {
      id: "msg-1",
      agentId: "claude-sonnet",
      content: "I think we should approach this carefully.",
      timestamp: new Date(),
      isDeliberation: true,
    },
    {
      id: "msg-2",
      agentId: "gemini-flash",
      content: "I agree, let me add some context.",
      timestamp: new Date(),
      isDeliberation: true,
    },
  ];

  const consensusMessage: AgentMessage = {
    id: "msg-consensus",
    agentId: "claude-sonnet",
    content: "Based on our discussion, here is our recommendation.",
    timestamp: new Date(),
    isConsensus: true,
  };

  const thread: AgentExchangeThread = {
    id: "thread-1",
    messages: deliberationMessages,
    isDeliberation: true,
    consensusMessage,
  };

  it("renders collapsed by default", () => {
    render(<DeliberationPanel thread={thread} agents={testAgents} />);
    expect(screen.getByText("Agent Discussion")).toBeInTheDocument();
    expect(screen.getByText("Consensus reached")).toBeInTheDocument();
    // Deliberation content should not be visible
    expect(screen.queryByText("I think we should approach this carefully.")).not.toBeInTheDocument();
  });

  it("expands when clicked", () => {
    render(<DeliberationPanel thread={thread} agents={testAgents} />);

    fireEvent.click(screen.getByText("Agent Discussion"));

    // Deliberation content should now be visible
    expect(screen.getByText("I think we should approach this carefully.")).toBeInTheDocument();
    expect(screen.getByText("I agree, let me add some context.")).toBeInTheDocument();
  });

  it("shows consensus section when expanded", () => {
    render(<DeliberationPanel thread={thread} agents={testAgents} defaultExpanded />);

    expect(screen.getByText("Final Consensus")).toBeInTheDocument();
    expect(screen.getByText("Based on our discussion, here is our recommendation.")).toBeInTheDocument();
  });

  it("shows message count", () => {
    render(<DeliberationPanel thread={thread} agents={testAgents} />);
    expect(screen.getByText("2 messages")).toBeInTheDocument();
  });

  it("shows 'Deliberating' when no consensus", () => {
    const threadWithoutConsensus: AgentExchangeThread = {
      ...thread,
      consensusMessage: undefined,
    };

    render(<DeliberationPanel thread={threadWithoutConsensus} agents={testAgents} />);
    expect(screen.getByText("Deliberating")).toBeInTheDocument();
  });
});
