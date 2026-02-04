export interface ModelOption {
  alias: string;
  model: string;
  hint: string;
  provider: "claude" | "gemini" | "openrouter";
}

export const MODEL_OPTIONS: ModelOption[] = [
  { alias: "sonnet", model: "claude-sonnet-4-5", hint: "Balanced", provider: "claude" },
  { alias: "opus", model: "claude-opus-4-5", hint: "Powerful", provider: "claude" },
  { alias: "haiku", model: "claude-haiku-4-5", hint: "Quick", provider: "claude" },
  { alias: "flash", model: "gemini-3-flash-preview", hint: "Fast", provider: "gemini" },
  { alias: "pro", model: "gemini-3-pro-preview", hint: "Reasoning", provider: "gemini" },
  // OpenRouter Models
  { alias: "or/grok", model: "openrouter/x-ai/grok-code-fast-1", hint: "Grok Code", provider: "openrouter" },
  { alias: "or/grok-fast", model: "openrouter/x-ai/grok-4.1-fast", hint: "Grok 4.1", provider: "openrouter" },
  { alias: "or/kimi", model: "openrouter/moonshotai/kimi-k2.5", hint: "Kimi K2.5", provider: "openrouter" },
  { alias: "or/gemini-flash", model: "openrouter/google/gemini-3-flash-preview", hint: "OR Flash", provider: "openrouter" },
  { alias: "or/gemini-pro", model: "openrouter/google/gemini-3-pro-preview", hint: "OR Pro", provider: "openrouter" },
  { alias: "or/minimax", model: "openrouter/minimax/minimax-m2.1", hint: "MiniMax", provider: "openrouter" },
];
