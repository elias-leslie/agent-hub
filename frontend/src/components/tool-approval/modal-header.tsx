import { Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ToolCall, RiskLevel } from "./types";
import {
  ShieldCheck,
  AlertTriangle,
  AlertOctagon,
} from "lucide-react";

const RISK_ICONS: Record<RiskLevel, typeof ShieldCheck> = {
  low: ShieldCheck,
  medium: AlertTriangle,
  high: AlertOctagon,
};

interface ModalHeaderProps {
  toolCall: ToolCall;
  queueLength: number;
  timeRemaining: number;
  isUrgent: boolean;
}

export function ModalHeader({
  toolCall,
  queueLength,
  timeRemaining,
  isUrgent,
}: ModalHeaderProps) {
  const RiskIcon = RISK_ICONS[toolCall.riskLevel];

  return (
    <div
      className={cn(
        "px-5 py-4 flex items-start gap-4",
        toolCall.riskLevel === "low" &&
          "bg-emerald-50 dark:bg-emerald-950/30",
        toolCall.riskLevel === "medium" &&
          "bg-amber-50 dark:bg-amber-950/30",
        toolCall.riskLevel === "high" && "bg-rose-50 dark:bg-rose-950/30",
      )}
    >
      <div
        className={cn(
          "p-2.5 rounded-xl",
          toolCall.riskLevel === "low" &&
            "bg-emerald-100 dark:bg-emerald-900/50",
          toolCall.riskLevel === "medium" &&
            "bg-amber-100 dark:bg-amber-900/50",
          toolCall.riskLevel === "high" &&
            "bg-rose-100 dark:bg-rose-900/50",
        )}
      >
        <RiskIcon
          className={cn(
            "h-6 w-6",
            toolCall.riskLevel === "low" &&
              "text-emerald-600 dark:text-emerald-400",
            toolCall.riskLevel === "medium" &&
              "text-amber-600 dark:text-amber-400",
            toolCall.riskLevel === "high" &&
              "text-rose-600 dark:text-rose-400",
          )}
        />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
            Tool Approval Required
          </h2>
          {queueLength > 0 && (
            <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-400">
              +{queueLength} more
            </span>
          )}
        </div>
        <p
          className={cn(
            "text-sm mt-0.5",
            toolCall.riskLevel === "low" &&
              "text-emerald-700 dark:text-emerald-400",
            toolCall.riskLevel === "medium" &&
              "text-amber-700 dark:text-amber-400",
            toolCall.riskLevel === "high" &&
              "text-rose-700 dark:text-rose-400",
          )}
        >
          {toolCall.riskLevel === "low" &&
            "Safe operation with minimal impact"}
          {toolCall.riskLevel === "medium" &&
            "Review parameters before approving"}
          {toolCall.riskLevel === "high" &&
            "Potentially destructive - review carefully"}
        </p>
      </div>

      <div
        className={cn(
          "flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-sm font-mono",
          isUrgent
            ? "bg-rose-100 text-rose-700 dark:bg-rose-900/50 dark:text-rose-400 animate-pulse"
            : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
        )}
      >
        <Clock className="h-4 w-4" />
        {timeRemaining}s
      </div>
    </div>
  );
}
