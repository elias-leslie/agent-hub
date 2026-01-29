export interface ModelOption {
  alias: string;
  model: string;
  hint: string;
  provider: "claude" | "gemini";
}

export const MODEL_OPTIONS: ModelOption[] = [
  { alias: "sonnet", model: "claude-sonnet-4-5", hint: "Balanced", provider: "claude" },
  { alias: "opus", model: "claude-opus-4-5", hint: "Powerful", provider: "claude" },
  { alias: "haiku", model: "claude-haiku-4-5", hint: "Quick", provider: "claude" },
  { alias: "flash", model: "gemini-3-flash-preview", hint: "Fast", provider: "gemini" },
  { alias: "pro", model: "gemini-3-pro-preview", hint: "Reasoning", provider: "gemini" },
];
