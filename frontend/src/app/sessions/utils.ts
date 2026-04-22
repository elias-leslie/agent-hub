import type { Session, SessionListItem } from "@/lib/api";
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

type ExecutionIdentitySource = Pick<
  SessionListItem | Session,
  | "provider"
  | "model"
  | "requested_provider"
  | "requested_model"
  | "effective_provider"
  | "effective_model"
  | "requested_model_display_name"
  | "effective_model_display_name"
  | "fallback_used"
  | "fallback_reason"
>;

function coalesceLabel(...values: Array<string | null | undefined>): string | null {
  for (const value of values) {
    if (value && value.trim().length > 0) {
      return value;
    }
  }
  return null;
}

export function getExecutionIdentity(source: ExecutionIdentitySource) {
  const requestedModel = coalesceLabel(
    source.requested_model_display_name,
    source.requested_model,
  );
  const effectiveModel = coalesceLabel(
    source.effective_model_display_name,
    source.effective_model,
    source.model,
  ) ?? source.model;
  const requestedProvider = coalesceLabel(source.requested_provider, source.provider);
  const effectiveProvider = coalesceLabel(
    source.effective_provider,
    source.provider,
  ) ?? source.provider;
  const showRequested = Boolean(requestedModel && requestedModel !== effectiveModel);
  const fallbackReason = coalesceLabel(source.fallback_reason);
  const fallbackUsed = Boolean(source.fallback_used || showRequested || fallbackReason);

  return {
    requestedModel,
    effectiveModel,
    requestedProvider,
    effectiveProvider,
    showRequested,
    fallbackUsed,
    fallbackReason,
  };
}
