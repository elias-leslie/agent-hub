import { useState } from "react";
import { Terminal } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ToolCall } from "./types";

interface ModalContentProps {
  toolCall: ToolCall;
  agentName?: string;
  rememberChoice: boolean;
  onRememberChoiceChange: (checked: boolean) => void;
}

export function ModalContent({
  toolCall,
  agentName,
  rememberChoice,
  onRememberChoiceChange,
}: ModalContentProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="px-5 py-4 space-y-4">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800">
          <Terminal className="h-5 w-5 text-slate-500 dark:text-slate-400" />
        </div>
        <div>
          <p className="text-xs text-slate-500 dark:text-slate-400 uppercase tracking-wider font-medium">
            Tool
          </p>
          <p className="font-mono font-semibold text-slate-900 dark:text-slate-100">
            {toolCall.toolName}
          </p>
        </div>
      </div>

      {agentName && (
        <div className="text-sm text-slate-500 dark:text-slate-400">
          Requested by:{" "}
          <span className="font-medium">{agentName}</span>
        </div>
      )}

      <div>
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center justify-between w-full text-left"
        >
          <p className="text-xs text-slate-500 dark:text-slate-400 uppercase tracking-wider font-medium">
            Parameters
          </p>
          <span className="text-xs text-slate-400 dark:text-slate-500">
            {isExpanded ? "Collapse" : "Expand"}
          </span>
        </button>
        <div
          className={cn(
            "mt-2 rounded-lg overflow-hidden transition-all",
            "bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700",
          )}
        >
          <pre
            className={cn(
              "p-3 text-xs font-mono text-slate-700 dark:text-slate-300 overflow-x-auto",
              !isExpanded && "max-h-24",
            )}
          >
            {JSON.stringify(toolCall.parameters, null, 2)}
          </pre>
        </div>
      </div>

      <label className="flex items-center gap-2 cursor-pointer group">
        <input
          type="checkbox"
          checked={rememberChoice}
          onChange={(e) => onRememberChoiceChange(e.target.checked)}
          className={cn(
            "h-4 w-4 rounded border-slate-300 dark:border-slate-600",
            "text-blue-600 focus:ring-blue-500",
          )}
        />
        <span className="text-sm text-slate-600 dark:text-slate-400 group-hover:text-slate-900 dark:group-hover:text-slate-200">
          Remember this choice for{" "}
          <span className="font-mono">{toolCall.toolName}</span>
        </span>
      </label>
    </div>
  );
}
