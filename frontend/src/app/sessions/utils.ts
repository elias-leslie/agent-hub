// Cost per 1M tokens (approximate, varies by model)
export const COST_PER_1M_INPUT: Record<string, number> = {
  "claude-opus-4-6": 15.0,
  "claude-sonnet-4-5": 3.0,
  "claude-haiku-4-5": 0.8,
  "gemini-3-pro": 1.25,
  "gemini-3-flash": 0.075,
  // OpenRouter (approximate averages)
  "openrouter/x-ai/grok": 2.0,
  "openrouter/moonshotai/kimi": 1.0,
  "openrouter/minimax": 1.0,
  "openrouter/google/gemini": 0.1,
  default: 2.0,
};

export const COST_PER_1M_OUTPUT: Record<string, number> = {
  "claude-opus-4-6": 75.0,
  "claude-sonnet-4-5": 15.0,
  "claude-haiku-4-5": 4.0,
  "gemini-3-pro": 5.0,
  "gemini-3-flash": 0.3,
  // OpenRouter
  "openrouter/x-ai/grok": 10.0,
  "openrouter/moonshotai/kimi": 5.0,
  "openrouter/minimax": 5.0,
  "openrouter/google/gemini": 0.4,
  default: 8.0,
};

export function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffSecs < 10) return "just now";
  if (diffSecs < 60) return `${diffSecs}s ago`;
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function formatTokens(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
  return tokens.toString();
}

export function formatTokenPair(input: number, output: number): string {
  if (input === 0 && output === 0) return "—";
  return `${formatTokens(input)} / ${formatTokens(output)}`;
}

export function estimateCost(model: string, inputTokens: number, outputTokens: number): number {
  // Normalize model name for lookup
  const normalizedModel = model.toLowerCase();
  let inputRate = COST_PER_1M_INPUT.default;
  let outputRate = COST_PER_1M_OUTPUT.default;

  for (const key of Object.keys(COST_PER_1M_INPUT)) {
    if (normalizedModel.includes(key)) {
      inputRate = COST_PER_1M_INPUT[key];
      outputRate = COST_PER_1M_OUTPUT[key];
      break;
    }
  }

  return (inputTokens * inputRate + outputTokens * outputRate) / 1_000_000;
}

export function formatCost(cost: number): string {
  if (cost === 0) return "—";
  if (cost < 0.0001) return "<$0.0001";
  if (cost < 0.01) return `$${cost.toFixed(4)}`;
  if (cost < 1) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(2)}`;
}

export function formatDuration(startDate: string, endDate: string): string {
  const start = new Date(startDate).getTime();
  const end = new Date(endDate).getTime();
  const diffMs = end - start;
  if (diffMs < 1000) return `${diffMs}ms`;
  if (diffMs < 60000) return `${(diffMs / 1000).toFixed(1)}s`;
  return `${Math.floor(diffMs / 60000)}m ${Math.floor((diffMs % 60000) / 1000)}s`;
}
