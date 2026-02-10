import { Gauge } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TokenBudget } from "./types";
import { formatTokens } from "./utils";
import { Section } from "./section";

interface TokenBudgetSectionProps {
  tokenBudget: TokenBudget;
  isExpanded: boolean;
  onToggle: () => void;
}

export function TokenBudgetSection({
  tokenBudget,
  isExpanded,
  onToggle,
}: TokenBudgetSectionProps) {
  const usagePercent = Math.min(
    100,
    (tokenBudget.used / tokenBudget.limit) * 100,
  );
  const isWarning = usagePercent > 70;
  const isDanger = usagePercent > 90;

  return (
    <Section
      title="Token Budget"
      icon={<Gauge className="h-4 w-4" />}
      isExpanded={isExpanded}
      onToggle={onToggle}
      testId="context-section-budget"
    >
      <div className="space-y-3">
        <div>
          <div className="flex justify-between text-xs text-slate-500 dark:text-slate-400 mb-1">
            <span>{formatTokens(tokenBudget.used)} used</span>
            <span>{formatTokens(tokenBudget.limit)} limit</span>
          </div>
          <div className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all",
                isDanger
                  ? "bg-red-500"
                  : isWarning
                    ? "bg-amber-500"
                    : "bg-emerald-500",
              )}
              style={{ width: `${usagePercent}%` }}
            />
          </div>
          <p
            className={cn(
              "text-xs mt-1",
              isDanger
                ? "text-red-600 dark:text-red-400"
                : isWarning
                  ? "text-amber-600 dark:text-amber-400"
                  : "text-slate-500 dark:text-slate-400",
            )}
          >
            {usagePercent.toFixed(1)}% used •{" "}
            {formatTokens(tokenBudget.limit - tokenBudget.used)} remaining
          </p>
        </div>

        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="p-2 rounded bg-slate-50 dark:bg-slate-800">
            <p className="text-slate-500 dark:text-slate-400">Input</p>
            <p className="font-mono text-slate-700 dark:text-slate-300">
              {formatTokens(tokenBudget.inputTokens)}
            </p>
          </div>
          <div className="p-2 rounded bg-slate-50 dark:bg-slate-800">
            <p className="text-slate-500 dark:text-slate-400">Output</p>
            <p className="font-mono text-slate-700 dark:text-slate-300">
              {formatTokens(tokenBudget.outputTokens)}
            </p>
          </div>
        </div>
      </div>
    </Section>
  );
}
