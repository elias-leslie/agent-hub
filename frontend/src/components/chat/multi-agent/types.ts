/**
 * Multi-agent chat types for Agent Hub.
 */

export type AgentProvider = "claude" | "gemini";

export interface Agent {
  id: string;
  name: string;
  shortName: string;
  provider: AgentProvider;
  model: string;
  persona?: string;
}

export interface AgentMessage {
  id: string;
  agentId: string;
  content: string;
  timestamp: Date;
  isDeliberation?: boolean;
  replyToAgentId?: string;
  isConsensus?: boolean;
}

export interface AgentExchangeThread {
  id: string;
  messages: AgentMessage[];
  isDeliberation: boolean;
  consensusMessage?: AgentMessage;
}

export type TurnState = "idle" | "thinking" | "responding" | "waiting";

export interface AgentTurnState {
  agentId: string;
  state: TurnState;
  startedAt?: Date;
}

// Provider-specific styling
export const AGENT_COLORS = {
  claude: {
    primary: "oklch(0.65 0.18 40)", // Warm terracotta orange
    secondary: "oklch(0.92 0.05 40)", // Light orange tint
    accent: "oklch(0.55 0.15 40)", // Darker orange
    text: "oklch(0.35 0.08 40)", // Dark orange-brown
    border: "oklch(0.85 0.08 40)", // Soft orange border
    gradient: "linear-gradient(135deg, oklch(0.95 0.04 40), oklch(0.90 0.06 45))",
  },
  gemini: {
    primary: "oklch(0.55 0.15 250)", // Deep blue
    secondary: "oklch(0.92 0.04 250)", // Light blue tint
    accent: "oklch(0.45 0.12 250)", // Darker blue
    text: "oklch(0.30 0.08 250)", // Dark navy
    border: "oklch(0.85 0.06 250)", // Soft blue border
    gradient: "linear-gradient(135deg, oklch(0.95 0.03 250), oklch(0.90 0.05 255))",
  },
} as const;

// Dark mode variants
export const AGENT_COLORS_DARK = {
  claude: {
    primary: "oklch(0.70 0.16 40)",
    secondary: "oklch(0.25 0.06 40)",
    accent: "oklch(0.80 0.14 40)",
    text: "oklch(0.90 0.04 40)",
    border: "oklch(0.35 0.08 40)",
    gradient: "linear-gradient(135deg, oklch(0.22 0.05 40), oklch(0.28 0.07 45))",
  },
  gemini: {
    primary: "oklch(0.65 0.14 250)",
    secondary: "oklch(0.22 0.05 250)",
    accent: "oklch(0.75 0.12 250)",
    text: "oklch(0.90 0.03 250)",
    border: "oklch(0.35 0.06 250)",
    gradient: "linear-gradient(135deg, oklch(0.20 0.04 250), oklch(0.26 0.06 255))",
  },
} as const;
