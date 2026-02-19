export interface ProviderInfo {
  id: string;
  name: string;
  hint: string;
  oauth?: boolean;
  supportsApiKey?: boolean;
}

export const PROVIDERS: readonly ProviderInfo[] = [
  { id: "claude", name: "Claude", hint: "OAuth via CLI — no key needed", oauth: true },
  { id: "codex", name: "Codex", hint: "ChatGPT subscription OAuth", oauth: true },
  { id: "gemini", name: "Gemini", hint: "Google AI — OAuth or API key", oauth: true, supportsApiKey: true },
  { id: "openai", name: "OpenAI", hint: "OpenAI platform API key" },
  { id: "openrouter", name: "OpenRouter", hint: "OpenRouter API key" },
  { id: "xai", name: "xAI", hint: "xAI (Grok) API key" },
  { id: "zhipu", name: "Zhipu", hint: "Zhipu AI (GLM) API key" },
  { id: "minimax", name: "MiniMax", hint: "MiniMax API key" },
] as const;

export const PROVIDER_COLORS: Record<string, { dot: string; bg: string }> = {
  claude:     { dot: "bg-amber-400",   bg: "border-amber-500/20" },
  codex:      { dot: "bg-emerald-400", bg: "border-emerald-500/20" },
  gemini:     { dot: "bg-blue-400",    bg: "border-blue-500/20" },
  openai:     { dot: "bg-green-400",   bg: "border-green-500/20" },
  openrouter: { dot: "bg-purple-400",  bg: "border-purple-500/20" },
  xai:        { dot: "bg-red-400",     bg: "border-red-500/20" },
  zhipu:      { dot: "bg-teal-400",    bg: "border-teal-500/20" },
  minimax:    { dot: "bg-orange-400",  bg: "border-orange-500/20" },
};
