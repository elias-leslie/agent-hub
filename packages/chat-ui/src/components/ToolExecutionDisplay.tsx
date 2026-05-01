import { useState } from "react";
import { ChevronDown, ChevronRight, Terminal } from "lucide-react";
import type { ToolExecution } from "../types/chat";
import { ToolExecutionItem } from "./ToolExecutionItem";
import { cn } from "../lib/utils";

/**
 * Display all tool executions for a message.
 */
export function ToolExecutionDisplay({ tools }: { tools: ToolExecution[] }) {
  const hasRunningTool = tools.some((tool) => tool.status === "running");
  const hasError = tools.some((tool) => tool.status === "error");
  const [isExpanded, setIsExpanded] = useState(hasRunningTool);
  const displayTools = isExpanded ? tools : tools.filter((tool) => tool.status === "running").slice(0, 2);
  const statusLabel = hasRunningTool ? "running" : hasError ? "needs review" : "complete";

  return (
    <div className="mb-3 rounded-md border border-border/70 bg-muted/35">
      <div className="flex items-center justify-between gap-2 px-3 py-2 text-xs text-muted-foreground">
        <div className="flex min-w-0 items-center gap-1.5">
          <Terminal className="h-3.5 w-3.5 shrink-0" />
          <span className="font-medium text-foreground/80">Tool executions</span>
          <span className="tabular-nums">({tools.length})</span>
          <span
            className={cn(
              "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em]",
              hasRunningTool
                ? "bg-amber-500/15 text-amber-500"
                : hasError
                  ? "bg-destructive/10 text-destructive"
                  : "bg-emerald-500/10 text-emerald-500",
            )}
          >
            {statusLabel}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setIsExpanded((value) => !value)}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-medium text-muted-foreground transition hover:bg-accent hover:text-accent-foreground"
        >
          {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          {isExpanded ? "Hide" : "Show"}
        </button>
      </div>
      {displayTools.length > 0 && (
        <div className="space-y-1 border-t border-border/60 px-2 py-2">
          {displayTools.map((tool) => (
            <ToolExecutionItem key={tool.id} tool={tool} />
          ))}
        </div>
      )}
    </div>
  );
}
