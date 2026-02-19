import {
  Terminal,
  FileEdit,
  FileText,
} from "lucide-react";
import { formatModelName, MODEL_ALIAS_ENTRIES } from "../lib/model-names";

export { formatModelName };

export const MODEL_ALIASES = MODEL_ALIAS_ENTRIES;

export function detectMentionedModel(content: string): { alias: string; model: string; label: string } | null {
  const mentionMatch = content.match(/@(\w+)/);
  if (!mentionMatch) return null;
  const alias = mentionMatch[1].toLowerCase();
  const modelInfo = MODEL_ALIAS_ENTRIES[alias];
  if (!modelInfo) return null;
  return { alias, ...modelInfo };
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
