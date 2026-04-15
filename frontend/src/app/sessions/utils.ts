import type { ModelCost } from "@/lib/models";
import { formatRelativeTime, formatTokens } from "@/lib/formatters";
import { estimateTokenCost } from "@/lib/model-pricing";

// Re-exported from canonical location
export { formatRelativeTime, formatTokens };


export function formatTokenPair(input: number, output: number): string {
  if (input === 0 && output === 0) return "—";
  return `${formatTokens(input)} / ${formatTokens(output)}`;
}

export function estimateCost(
  model: string,
  inputTokens: number,
  outputTokens: number,
  modelCosts: Map<string, ModelCost>,
): number {
  return estimateTokenCost(model, inputTokens, outputTokens, modelCosts);
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
