import { useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Loader2,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import type { ToolExecution } from "@/types/chat";
import { cn } from "@/lib/utils";
import { getToolIcon } from "./message-utils";

/**
 * Display a single tool execution with status and result.
 */
export function ToolExecutionItem({ tool }: { tool: ToolExecution }) {
  const [expanded, setExpanded] = useState(false);
  const Icon = getToolIcon(tool.name);

  return (
    <div
      className={cn(
        "rounded-md border text-xs",
        tool.status === "running"
          ? "bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/50"
          : tool.status === "error"
            ? "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-900/50"
            : "bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-900/50",
      )}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left"
      >
        <Icon
          className={cn(
            "h-3.5 w-3.5 flex-shrink-0",
            tool.status === "running"
              ? "text-amber-600 dark:text-amber-400"
              : tool.status === "error"
                ? "text-red-600 dark:text-red-400"
                : "text-emerald-600 dark:text-emerald-400",
          )}
        />
        <span className="font-medium text-slate-700 dark:text-slate-300 flex-1">
          {tool.name}
        </span>
        {tool.status === "running" ? (
          <Loader2 className="h-3.5 w-3.5 text-amber-500 animate-spin" />
        ) : tool.status === "error" ? (
          <AlertCircle className="h-3.5 w-3.5 text-red-500" />
        ) : (
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
        )}
        {expanded ? (
          <ChevronUp className="h-3 w-3 text-slate-400" />
        ) : (
          <ChevronDown className="h-3 w-3 text-slate-400" />
        )}
      </button>

      {expanded && (
        <div className="px-2.5 pb-2 space-y-1.5">
          {/* Input */}
          <div className="text-slate-500 dark:text-slate-400">
            <span className="font-medium">Input: </span>
            <code className="text-[10px] bg-white/50 dark:bg-black/20 px-1 py-0.5 rounded">
              {JSON.stringify(tool.input, null, 2).slice(0, 200)}
              {JSON.stringify(tool.input).length > 200 && "..."}
            </code>
          </div>

          {/* Result */}
          {tool.result && (
            <div className="text-slate-500 dark:text-slate-400">
              <span className="font-medium">Result: </span>
              <pre className="text-[10px] bg-white/50 dark:bg-black/20 p-1.5 rounded mt-0.5 overflow-x-auto max-h-24 whitespace-pre-wrap break-all">
                {tool.result.slice(0, 500)}
                {tool.result.length > 500 && "\n... (truncated)"}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
