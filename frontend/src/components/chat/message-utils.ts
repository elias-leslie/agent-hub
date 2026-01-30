import {
  Terminal,
  FileEdit,
  FileText,
} from "lucide-react";

export const MODEL_ALIASES: Record<string, { model: string; label: string }> = {
  sonnet: { model: "claude-sonnet-4-5", label: "Sonnet" },
  opus: { model: "claude-opus-4-5", label: "Opus" },
  haiku: { model: "claude-haiku-4-5", label: "Haiku" },
  flash: { model: "gemini-3-flash-preview", label: "Flash" },
  pro: { model: "gemini-3-pro-preview", label: "Pro" },
};

export function detectMentionedModel(content: string): { alias: string; model: string; label: string } | null {
  const mentionMatch = content.match(/@(\w+)/);
  if (!mentionMatch) return null;
  const alias = mentionMatch[1].toLowerCase();
  const modelInfo = MODEL_ALIASES[alias];
  if (!modelInfo) return null;
  return { alias, ...modelInfo };
}

/** Format model ID to human-readable name */
export function formatModelName(modelId?: string): string {
  if (!modelId) return "Assistant";

  // Model ID to friendly name mapping
  const modelNames: Record<string, string> = {
    "claude-sonnet-4-5-20250514": "Claude Sonnet 4.5",
    "claude-sonnet-4-5": "Claude Sonnet 4.5",
    "claude-opus-4-5-20250514": "Claude Opus 4.5",
    "claude-opus-4-5": "Claude Opus 4.5",
    "claude-haiku-4-5-20250514": "Claude Haiku 4.5",
    "claude-haiku-4-5": "Claude Haiku 4.5",
    "gemini-3-flash-preview": "Gemini 3 Flash",
    "gemini-3-pro-preview": "Gemini 3 Pro",
  };

  return modelNames[modelId] || modelId;
}

/**
 * Get icon for tool based on its name.
 */
export function getToolIcon(toolName: string) {
  const name = toolName.toLowerCase();
  if (name.includes("bash") || name.includes("command")) {
    return Terminal;
  }
  if (name.includes("write") || name.includes("edit")) {
    return FileEdit;
  }
  return FileText; // Default to file icon for Read and other tools
}

/**
 * Group messages by responseGroupId for parallel responses.
 */
export function groupMessages(messages: any[]): Array<any | any[]> {
  const groupedMessages: Array<any | any[]> = [];
  let currentGroup: any[] = [];
  let currentGroupId: string | undefined;

  for (const message of messages) {
    if (message.responseGroupId) {
      if (message.responseGroupId === currentGroupId) {
        currentGroup.push(message);
      } else {
        if (currentGroup.length > 0) {
          groupedMessages.push(currentGroup.length === 1 ? currentGroup[0] : currentGroup);
        }
        currentGroup = [message];
        currentGroupId = message.responseGroupId;
      }
    } else {
      if (currentGroup.length > 0) {
        groupedMessages.push(currentGroup.length === 1 ? currentGroup[0] : currentGroup);
        currentGroup = [];
        currentGroupId = undefined;
      }
      groupedMessages.push(message);
    }
  }
  if (currentGroup.length > 0) {
    groupedMessages.push(currentGroup.length === 1 ? currentGroup[0] : currentGroup);
  }

  return groupedMessages;
}
