export interface ContextSource {
  id: string;
  type: "message" | "system" | "memory" | "summary";
  label: string;
  content: string;
  tokens?: number;
  timestamp?: Date;
  originalContent?: string; // For summarized content
}

export interface TokenBudget {
  used: number;
  limit: number;
  inputTokens: number;
  outputTokens: number;
}

export interface StickyNote {
  id: string;
  content: string;
  createdAt: Date;
}

export interface ContextPanelProps {
  isOpen: boolean;
  onToggle: () => void;
  sources: ContextSource[];
  tokenBudget: TokenBudget;
  systemPrompt?: string;
  stickyNotes: StickyNote[];
  onAddNote: (content: string) => void;
  onRemoveNote: (id: string) => void;
}
