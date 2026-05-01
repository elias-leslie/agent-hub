import type { ChatMessage } from "../types/chat";

/**
 * Returns bubble styling for a chat message.
 *
 * Uses theme tokens for surfaces and a small provider accent for recognition.
 */
export function getProviderBubbleStyle(message: ChatMessage, isUser: boolean): string {
  if (isUser) {
    return "bg-primary text-primary-foreground shadow-sm";
  }

  const provider = message.agentProvider;
  const styles: Record<string, string> = {
    claude: "border border-border bg-card/85 text-card-foreground shadow-sm border-l-2 border-l-orange-500/70",
    gemini: "border border-border bg-card/85 text-card-foreground shadow-sm border-l-2 border-l-blue-500/70",
    openai: "border border-border bg-card/85 text-card-foreground shadow-sm border-l-2 border-l-emerald-500/70",
    openrouter: "border border-border bg-card/85 text-card-foreground shadow-sm border-l-2 border-l-violet-500/70",
    xai: "border border-border bg-card/85 text-card-foreground shadow-sm border-l-2 border-l-rose-500/70",
    zhipu: "border border-border bg-card/85 text-card-foreground shadow-sm border-l-2 border-l-teal-500/70",
  };

  return (provider && styles[provider]) || "border border-border bg-card/85 text-card-foreground shadow-sm";
}

export function getProviderIconColor(provider?: string): string {
  const colors: Record<string, string> = {
    claude: "text-orange-400",
    gemini: "text-blue-400",
    openai: "text-emerald-400",
    openrouter: "text-violet-400",
    xai: "text-red-400",
    zhipu: "text-teal-400",
  };

  return (provider && colors[provider]) || "text-gray-400";
}

export function getProviderTextColor(provider?: string): string {
  const colors: Record<string, string> = {
    claude: "text-orange-400",
    gemini: "text-blue-400",
    openai: "text-emerald-400",
    openrouter: "text-violet-400",
    xai: "text-red-400",
    zhipu: "text-teal-400",
  };

  return (provider && colors[provider]) || "text-gray-400";
}
