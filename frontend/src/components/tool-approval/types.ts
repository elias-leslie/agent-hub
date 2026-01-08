/**
 * Tool approval types for Agent Hub.
 */

export type RiskLevel = "low" | "medium" | "high";

export type ApprovalDecision =
  | "approve"
  | "approve_all"
  | "deny"
  | "deny_all"
  | "timeout";

export interface ToolCall {
  id: string;
  toolName: string;
  parameters: Record<string, unknown>;
  riskLevel: RiskLevel;
  description?: string;
  estimatedDuration?: string;
  timestamp: Date;
}

export interface ApprovalRequest {
  id: string;
  toolCall: ToolCall;
  timeoutSeconds: number;
  agentId?: string;
  agentName?: string;
}

export interface ApprovalResponse {
  requestId: string;
  decision: ApprovalDecision;
  rememberChoice: boolean;
  timestamp: Date;
}

export interface SavedPreference {
  toolName: string;
  decision: "approve" | "deny";
  savedAt: Date;
}

// Risk level styling configurations
export const RISK_CONFIG: Record<
  RiskLevel,
  {
    label: string;
    description: string;
    bgColor: string;
    textColor: string;
    borderColor: string;
    icon: string;
  }
> = {
  low: {
    label: "Low Risk",
    description: "Safe operation with minimal impact",
    bgColor: "bg-emerald-50 dark:bg-emerald-950/30",
    textColor: "text-emerald-700 dark:text-emerald-400",
    borderColor: "border-emerald-200 dark:border-emerald-800",
    icon: "shield-check",
  },
  medium: {
    label: "Medium Risk",
    description: "Review parameters before approving",
    bgColor: "bg-amber-50 dark:bg-amber-950/30",
    textColor: "text-amber-700 dark:text-amber-400",
    borderColor: "border-amber-200 dark:border-amber-800",
    icon: "alert-triangle",
  },
  high: {
    label: "High Risk",
    description: "Potentially destructive or irreversible",
    bgColor: "bg-rose-50 dark:bg-rose-950/30",
    textColor: "text-rose-700 dark:text-rose-400",
    borderColor: "border-rose-200 dark:border-rose-800",
    icon: "alert-octagon",
  },
};
