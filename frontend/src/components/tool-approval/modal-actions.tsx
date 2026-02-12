import { Check, Ban, CheckCheck, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ApprovalDecision } from "./types";

interface ModalActionsProps {
  onDecision: (decision: ApprovalDecision) => void;
}

export function ModalActions({ onDecision }: ModalActionsProps) {
  return (
    <div className="px-5 py-4 bg-slate-50 dark:bg-slate-800/50 border-t border-slate-200 dark:border-slate-700">
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => onDecision("approve")}
          className={cn(
            "flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg",
            "bg-emerald-600 text-white font-medium",
            "hover:bg-emerald-700 transition-colors",
            "focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2",
          )}
        >
          <Check className="h-4 w-4" />
          <span>Approve</span>
          <kbd className="ml-1 px-1.5 py-0.5 text-xs rounded bg-emerald-700/50">
            Y
          </kbd>
        </button>

        <button
          onClick={() => onDecision("deny")}
          className={cn(
            "flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg",
            "bg-rose-600 text-white font-medium",
            "hover:bg-rose-700 transition-colors",
            "focus:outline-none focus:ring-2 focus:ring-rose-500 focus:ring-offset-2",
          )}
        >
          <Ban className="h-4 w-4" />
          <span>Deny</span>
          <kbd className="ml-1 px-1.5 py-0.5 text-xs rounded bg-rose-700/50">
            N
          </kbd>
        </button>
      </div>

      <div className="flex gap-2 mt-2">
        <button
          onClick={() => onDecision("approve_all")}
          className={cn(
            "flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm",
            "bg-amber-100 text-amber-700 font-medium",
            "hover:bg-amber-200 dark:bg-amber-900/40 dark:text-amber-400 dark:hover:bg-amber-900/60",
            "transition-colors",
          )}
        >
          <CheckCheck className="h-4 w-4" />
          <span>Approve All (YOLO)</span>
          <kbd className="ml-1 px-1 py-0.5 text-xs rounded bg-amber-200 dark:bg-amber-800">
            ⇧A
          </kbd>
        </button>

        <button
          onClick={() => onDecision("deny_all")}
          className={cn(
            "flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm",
            "bg-slate-200 text-slate-700 font-medium",
            "hover:bg-slate-300 dark:bg-slate-700 dark:text-slate-300 dark:hover:bg-slate-600",
            "transition-colors",
          )}
        >
          <XCircle className="h-4 w-4" />
          <span>Deny All</span>
          <kbd className="ml-1 px-1 py-0.5 text-xs rounded bg-slate-300 dark:bg-slate-600">
            ⇧D
          </kbd>
        </button>
      </div>
    </div>
  );
}
