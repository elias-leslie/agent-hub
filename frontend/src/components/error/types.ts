/**
 * Error handling types for Agent Hub.
 */

export type ErrorType =
  | "rate_limit"
  | "provider_down"
  | "context_overflow"
  | "tool_failed"
  | "network"
  | "auth"
  | "unknown";

export type ErrorSeverity = "warning" | "error" | "critical";

export interface AppError {
  id: string;
  type: ErrorType;
  severity: ErrorSeverity;
  title: string;
  message: string;
  details?: string;
  timestamp: Date;
  retryable: boolean;
  modelSpecific?: boolean;
  suggestedActions?: SuggestedAction[];
}

export interface SuggestedAction {
  id: string;
  label: string;
  description?: string;
  action: "retry" | "switch_model" | "reduce_context" | "contact_support" | "dismiss" | "custom";
  primary?: boolean;
}

// Error type configurations
export const ERROR_CONFIG: Record<
  ErrorType,
  {
    severity: ErrorSeverity;
    title: string;
    icon: string;
    retryable: boolean;
    modelSpecific: boolean;
    suggestedActions: SuggestedAction[];
  }
> = {
  rate_limit: {
    severity: "warning",
    title: "Rate Limit Reached",
    icon: "clock",
    retryable: true,
    modelSpecific: true,
    suggestedActions: [
      { id: "wait", label: "Wait & Retry", action: "retry", primary: true },
      { id: "switch", label: "Try Different Model", action: "switch_model" },
    ],
  },
  provider_down: {
    severity: "error",
    title: "Provider Unavailable",
    icon: "cloud-off",
    retryable: true,
    modelSpecific: true,
    suggestedActions: [
      { id: "switch", label: "Switch Provider", action: "switch_model", primary: true },
      { id: "retry", label: "Retry", action: "retry" },
    ],
  },
  context_overflow: {
    severity: "warning",
    title: "Context Too Long",
    icon: "file-text",
    retryable: false,
    modelSpecific: false,
    suggestedActions: [
      { id: "reduce", label: "Reduce Context", action: "reduce_context", primary: true },
      { id: "switch", label: "Try Larger Model", action: "switch_model" },
    ],
  },
  tool_failed: {
    severity: "error",
    title: "Tool Execution Failed",
    icon: "wrench",
    retryable: true,
    modelSpecific: false,
    suggestedActions: [
      { id: "retry", label: "Retry", action: "retry", primary: true },
      { id: "skip", label: "Skip Tool", action: "dismiss" },
    ],
  },
  network: {
    severity: "warning",
    title: "Connection Issue",
    icon: "wifi-off",
    retryable: true,
    modelSpecific: false,
    suggestedActions: [
      { id: "retry", label: "Retry Connection", action: "retry", primary: true },
    ],
  },
  auth: {
    severity: "error",
    title: "Authentication Error",
    icon: "key",
    retryable: false,
    modelSpecific: false,
    suggestedActions: [
      { id: "reauth", label: "Re-authenticate", action: "custom", primary: true },
    ],
  },
  unknown: {
    severity: "error",
    title: "Something Went Wrong",
    icon: "alert-circle",
    retryable: true,
    modelSpecific: false,
    suggestedActions: [
      { id: "retry", label: "Try Again", action: "retry", primary: true },
      { id: "support", label: "Contact Support", action: "contact_support" },
    ],
  },
};

// Helper to create error from type
export function createAppError(
  type: ErrorType,
  message: string,
  details?: string
): AppError {
  const config = ERROR_CONFIG[type];
  return {
    id: `err-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    type,
    severity: config.severity,
    title: config.title,
    message,
    details,
    timestamp: new Date(),
    retryable: config.retryable,
    modelSpecific: config.modelSpecific,
    suggestedActions: config.suggestedActions,
  };
}
