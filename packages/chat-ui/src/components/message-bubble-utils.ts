import type { ChatMessage } from "../types/chat";

/**
 * Returns bubble styling for a chat message.
 *
 * Dark-mode only — no light-mode classes. Uses simple bg + border-l accent
 * instead of gradients to avoid tailwind-merge stripping conflicting utilities.
 */
export function getProviderBubbleStyle(message: ChatMessage, isUser: boolean): string {
  if (isUser) {
    return "bg-blue-600 text-white";
  }

  const provider = message.agentProvider;
  const styles: Record<string, string> = {
    claude: "bg-orange-950/25 border-l-2 border-l-orange-500/60 text-gray-100",
    gemini: "bg-blue-950/25 border-l-2 border-l-blue-500/60 text-gray-100",
    openai: "bg-green-950/25 border-l-2 border-l-green-500/60 text-gray-100",
    xai: "bg-red-950/25 border-l-2 border-l-red-500/60 text-gray-100",
    zhipu: "bg-teal-950/25 border-l-2 border-l-teal-500/60 text-gray-100",
  };

  return (provider && styles[provider]) || "bg-gray-800 text-gray-100";
}

export function getProviderIconColor(provider?: string): string {
  const colors: Record<string, string> = {
    claude: "text-orange-400",
    gemini: "text-blue-400",
    openai: "text-green-400",
    xai: "text-red-400",
    zhipu: "text-teal-400",
  };

  return (provider && colors[provider]) || "text-gray-400";
}

export function getProviderTextColor(provider?: string): string {
  const colors: Record<string, string> = {
    claude: "text-orange-400",
    gemini: "text-blue-400",
    openai: "text-green-400",
    xai: "text-red-400",
    zhipu: "text-teal-400",
  };

  return (provider && colors[provider]) || "text-gray-400";
}
