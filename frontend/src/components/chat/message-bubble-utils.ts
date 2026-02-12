import type { ChatMessage } from "@/types/chat";

export function getProviderBubbleStyle(message: ChatMessage, isUser: boolean): string {
  if (isUser) {
    return "bg-blue-500 text-white";
  }

  const provider = message.agentProvider;
  const baseStyles: Record<string, string> = {
    claude: "bg-gradient-to-br from-orange-50 to-amber-50/50 border border-orange-100 dark:from-orange-950/30 dark:to-amber-950/20 dark:border-orange-900/30 text-gray-900 dark:text-gray-100",
    gemini: "bg-gradient-to-br from-blue-50 to-indigo-50/50 border border-blue-100 dark:from-blue-950/30 dark:to-indigo-950/20 dark:border-blue-900/30 text-gray-900 dark:text-gray-100",
    openai: "bg-gradient-to-br from-green-50 to-emerald-50/50 border border-green-100 dark:from-green-950/30 dark:to-emerald-950/20 dark:border-green-900/30 text-gray-900 dark:text-gray-100",
    xai: "bg-gradient-to-br from-red-50 to-rose-50/50 border border-red-100 dark:from-red-950/30 dark:to-rose-950/20 dark:border-red-900/30 text-gray-900 dark:text-gray-100",
    zhipu: "bg-gradient-to-br from-teal-50 to-cyan-50/50 border border-teal-100 dark:from-teal-950/30 dark:to-cyan-950/20 dark:border-teal-900/30 text-gray-900 dark:text-gray-100",
  };

  return provider && baseStyles[provider]
    ? baseStyles[provider]
    : "bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100";
}

export function getProviderIconColor(provider?: string): string {
  const colors: Record<string, string> = {
    claude: "text-orange-500 dark:text-orange-400",
    gemini: "text-blue-500 dark:text-blue-400",
    openai: "text-green-500 dark:text-green-400",
    xai: "text-red-500 dark:text-red-400",
    zhipu: "text-teal-500 dark:text-teal-400",
  };

  return provider && colors[provider] ? colors[provider] : "";
}

export function getProviderTextColor(provider?: string): string {
  const colors: Record<string, string> = {
    claude: "text-orange-600 dark:text-orange-400",
    gemini: "text-blue-600 dark:text-blue-400",
    openai: "text-green-600 dark:text-green-400",
    xai: "text-red-600 dark:text-red-400",
    zhipu: "text-teal-600 dark:text-teal-400",
  };

  return provider && colors[provider] ? colors[provider] : "text-gray-600 dark:text-gray-400";
}
