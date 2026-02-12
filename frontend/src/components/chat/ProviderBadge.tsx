import { Cpu, Sparkles } from "lucide-react";
import type { ChatMessage } from "@/types/chat";
import { cn } from "@/lib/utils";
import { formatModelName } from "./message-utils";
import { getProviderIconColor, getProviderTextColor } from "./message-bubble-utils";

interface ProviderBadgeProps {
  message: ChatMessage;
}

export function ProviderBadge({ message }: ProviderBadgeProps) {
  if (!message.agentModel && !message.agentName) {
    return null;
  }

  const provider = message.agentProvider;

  const getIcon = () => {
    if (provider === "gemini") {
      return <Sparkles className={cn("h-3.5 w-3.5", getProviderIconColor(provider))} />;
    }
    return <Cpu className={cn("h-3.5 w-3.5", getProviderIconColor(provider))} />;
  };

  return (
    <div className="flex items-center gap-1.5 mb-2 pb-2 border-b border-current/10">
      {getIcon()}
      <span className={cn("text-xs font-semibold", getProviderTextColor(provider))}>
        {message.agentName || formatModelName(message.agentModel)}
      </span>
      {message.isDeliberation && (
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-200/50 text-slate-500 dark:bg-slate-700/50 dark:text-slate-400">
          deliberation
        </span>
      )}
      {message.isConsensus && (
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-600 dark:bg-emerald-900/50 dark:text-emerald-400 font-medium">
          consensus
        </span>
      )}
    </div>
  );
}
