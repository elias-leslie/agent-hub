import { Cpu, Sparkles } from "lucide-react";
import type { ChatMessage } from "../types/chat";
import { cn } from "../lib/utils";
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
        {message.agentName && message.agentModel
          ? `${message.agentName} (${formatModelName(message.agentModel)})`
          : message.agentModel
            ? formatModelName(message.agentModel)
            : (message.agentName || "Assistant")}
      </span>
      {message.isDeliberation && (
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
          deliberation
        </span>
      )}
      {message.isConsensus && (
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/50 text-emerald-400 font-medium">
          consensus
        </span>
      )}
    </div>
  );
}
