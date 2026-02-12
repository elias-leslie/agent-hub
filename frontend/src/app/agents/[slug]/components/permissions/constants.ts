import {
  ShieldCheck,
  ShieldAlert,
  ShieldQuestion,
} from "lucide-react";

export type PermissionMode = "yolo" | "ask" | "granular";

export const MODE_CONFIG: Record<
  PermissionMode,
  {
    label: string;
    description: string;
    icon: React.ElementType;
    color: string;
    bg: string;
  }
> = {
  yolo: {
    label: "Auto-Approve",
    description: "Automatically approve all tool calls without confirmation",
    icon: ShieldCheck,
    color: "text-emerald-400",
    bg: "bg-emerald-950/30 border-emerald-500/30",
  },
  ask: {
    label: "Confirm All",
    description: "Require manual confirmation for every tool call",
    icon: ShieldQuestion,
    color: "text-amber-400",
    bg: "bg-amber-950/30 border-amber-500/30",
  },
  granular: {
    label: "Granular",
    description: "Configure permissions per tool with allow/deny lists",
    icon: ShieldAlert,
    color: "text-blue-400",
    bg: "bg-blue-950/30 border-blue-500/30",
  },
};

export const COMMON_TOOLS = [
  { name: "bash", description: "Execute shell commands", risk: "high" },
  { name: "read_file", description: "Read file contents", risk: "low" },
  { name: "write_file", description: "Write/create files", risk: "medium" },
  { name: "edit_file", description: "Edit existing files", risk: "medium" },
  { name: "glob", description: "Search for files by pattern", risk: "low" },
  { name: "grep", description: "Search file contents", risk: "low" },
  { name: "web_fetch", description: "Fetch web content", risk: "medium" },
  { name: "web_search", description: "Search the web", risk: "low" },
] as const;
