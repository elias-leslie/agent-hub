import { useState } from "react";
import {
  Shield,
  ShieldCheck,
  ShieldAlert,
  ShieldQuestion,
  Plus,
  X,
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Agent, PermissionConfig } from "../types";

// Common tools that agents might use
const COMMON_TOOLS = [
  { name: "bash", description: "Execute shell commands", risk: "high" },
  { name: "read_file", description: "Read file contents", risk: "low" },
  { name: "write_file", description: "Write/create files", risk: "medium" },
  { name: "edit_file", description: "Edit existing files", risk: "medium" },
  { name: "glob", description: "Search for files by pattern", risk: "low" },
  { name: "grep", description: "Search file contents", risk: "low" },
  { name: "web_fetch", description: "Fetch web content", risk: "medium" },
  { name: "web_search", description: "Search the web", risk: "low" },
] as const;

type PermissionMode = "yolo" | "ask" | "granular";

const MODE_CONFIG: Record<
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

interface PermissionsTabProps {
  formData: Partial<Agent>;
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void;
}

export function PermissionsTab({ formData, updateField }: PermissionsTabProps) {
  const [newAllowTool, setNewAllowTool] = useState("");
  const [newDenyTool, setNewDenyTool] = useState("");

  // Get or create default permission config
  const config: PermissionConfig = formData.tool_permissions || {
    mode: "yolo",
    tool_permissions: {},
    allow_list: [],
    deny_list: [],
  };

  const updateConfig = (updates: Partial<PermissionConfig>) => {
    updateField("tool_permissions", { ...config, ...updates });
  };

  const setMode = (mode: PermissionMode) => {
    updateConfig({ mode });
  };

  const addToAllowList = (tool: string) => {
    if (!tool.trim()) return;
    const newList = [...new Set([...config.allow_list, tool.trim()])];
    // Remove from deny list if present
    const newDenyList = config.deny_list.filter((t) => t !== tool.trim());
    updateConfig({ allow_list: newList, deny_list: newDenyList });
    setNewAllowTool("");
  };

  const addToDenyList = (tool: string) => {
    if (!tool.trim()) return;
    const newList = [...new Set([...config.deny_list, tool.trim()])];
    // Remove from allow list if present
    const newAllowList = config.allow_list.filter((t) => t !== tool.trim());
    updateConfig({ deny_list: newList, allow_list: newAllowList });
    setNewDenyTool("");
  };

  const removeFromAllowList = (tool: string) => {
    updateConfig({ allow_list: config.allow_list.filter((t) => t !== tool) });
  };

  const removeFromDenyList = (tool: string) => {
    updateConfig({ deny_list: config.deny_list.filter((t) => t !== tool) });
  };

  // Calculate effective permission for a tool
  const getEffectivePermission = (
    toolName: string
  ): "allow" | "deny" | "ask" => {
    // Check per-tool permissions first
    const toolPerm = config.tool_permissions[toolName];
    if (toolPerm) {
      if (!toolPerm.allowed) return "deny";
      if (toolPerm.requires_confirmation) return "ask";
      return "allow";
    }

    // Check deny list
    if (config.deny_list.includes(toolName)) return "deny";

    // Check allow list (in granular mode)
    if (config.mode === "granular" && config.allow_list.includes(toolName)) {
      return "allow";
    }

    // Apply global mode
    if (config.mode === "yolo") return "allow";
    if (config.mode === "ask") return "ask";
    return "ask"; // Granular mode default
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-slate-100 flex items-center gap-2">
          <Shield className="h-5 w-5 text-slate-400" />
          Tool Permissions
        </h2>
        <p className="text-sm text-slate-400 mt-1">
          Control which tools this agent can use and whether confirmation is
          required
        </p>
      </div>

      {/* Mode Selection */}
      <div className="space-y-3">
        <label className="text-sm font-medium text-slate-300">
          Permission Mode
        </label>
        <div className="grid grid-cols-3 gap-3">
          {(Object.keys(MODE_CONFIG) as PermissionMode[]).map((mode) => {
            const modeConfig = MODE_CONFIG[mode];
            const isActive = config.mode === mode;
            const Icon = modeConfig.icon;

            return (
              <button
                key={mode}
                onClick={() => setMode(mode)}
                className={cn(
                  "relative flex flex-col items-center gap-2 p-4 rounded-lg border-2 transition-all",
                  isActive
                    ? modeConfig.bg
                    : "bg-slate-900/50 border-slate-700 hover:border-slate-600"
                )}
              >
                <Icon
                  className={cn(
                    "h-6 w-6",
                    isActive ? modeConfig.color : "text-slate-500"
                  )}
                />
                <span
                  className={cn(
                    "text-sm font-medium",
                    isActive ? "text-slate-100" : "text-slate-400"
                  )}
                >
                  {modeConfig.label}
                </span>
                <span
                  className={cn(
                    "text-xs text-center",
                    isActive ? "text-slate-400" : "text-slate-500"
                  )}
                >
                  {modeConfig.description}
                </span>
                {isActive && (
                  <div
                    className={cn(
                      "absolute top-2 right-2 h-2 w-2 rounded-full",
                      mode === "yolo"
                        ? "bg-emerald-400"
                        : mode === "ask"
                          ? "bg-amber-400"
                          : "bg-blue-400"
                    )}
                  />
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Granular Mode Configuration */}
      {config.mode === "granular" && (
        <div className="space-y-6 pt-4 border-t border-slate-800">
          {/* Allow List */}
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              <label className="text-sm font-medium text-slate-300">
                Allow List
              </label>
              <span className="text-xs text-slate-500">
                (auto-approve these tools)
              </span>
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={newAllowTool}
                onChange={(e) => setNewAllowTool(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addToAllowList(newAllowTool)}
                placeholder="Tool name (e.g., read_file)"
                className="flex-1 px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
              />
              <button
                onClick={() => addToAllowList(newAllowTool)}
                className="px-3 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-sm font-medium flex items-center gap-1"
              >
                <Plus className="h-4 w-4" />
                Add
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {config.allow_list.map((tool) => (
                <span
                  key={tool}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-emerald-950/40 border border-emerald-500/30 rounded-full text-sm text-emerald-300"
                >
                  {tool}
                  <button
                    onClick={() => removeFromAllowList(tool)}
                    className="hover:text-emerald-100"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
              {config.allow_list.length === 0 && (
                <span className="text-xs text-slate-500 italic">
                  No tools in allow list
                </span>
              )}
            </div>
          </div>

          {/* Deny List */}
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-red-400" />
              <label className="text-sm font-medium text-slate-300">
                Deny List
              </label>
              <span className="text-xs text-slate-500">
                (block these tools)
              </span>
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={newDenyTool}
                onChange={(e) => setNewDenyTool(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addToDenyList(newDenyTool)}
                placeholder="Tool name (e.g., bash)"
                className="flex-1 px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-red-500/50"
              />
              <button
                onClick={() => addToDenyList(newDenyTool)}
                className="px-3 py-2 bg-red-600 hover:bg-red-500 text-white rounded-lg text-sm font-medium flex items-center gap-1"
              >
                <Plus className="h-4 w-4" />
                Add
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {config.deny_list.map((tool) => (
                <span
                  key={tool}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-red-950/40 border border-red-500/30 rounded-full text-sm text-red-300"
                >
                  {tool}
                  <button
                    onClick={() => removeFromDenyList(tool)}
                    className="hover:text-red-100"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
              {config.deny_list.length === 0 && (
                <span className="text-xs text-slate-500 italic">
                  No tools in deny list
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Effective Permissions Preview */}
      <div className="space-y-3 pt-4 border-t border-slate-800">
        <div className="flex items-center gap-2">
          <HelpCircle className="h-4 w-4 text-slate-400" />
          <label className="text-sm font-medium text-slate-300">
            Effective Permissions Preview
          </label>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {COMMON_TOOLS.map((tool) => {
            const effective = getEffectivePermission(tool.name);
            return (
              <div
                key={tool.name}
                className={cn(
                  "flex items-center justify-between px-3 py-2 rounded-lg border",
                  effective === "allow"
                    ? "bg-emerald-950/20 border-emerald-500/20"
                    : effective === "deny"
                      ? "bg-red-950/20 border-red-500/20"
                      : "bg-amber-950/20 border-amber-500/20"
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="text-sm text-slate-300 font-mono">
                    {tool.name}
                  </span>
                  {tool.risk === "high" && (
                    <span className="text-[10px] px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded uppercase font-semibold">
                      high risk
                    </span>
                  )}
                </div>
                <span
                  className={cn(
                    "text-xs font-medium uppercase",
                    effective === "allow"
                      ? "text-emerald-400"
                      : effective === "deny"
                        ? "text-red-400"
                        : "text-amber-400"
                  )}
                >
                  {effective}
                </span>
              </div>
            );
          })}
        </div>
        <p className="text-xs text-slate-500">
          {config.mode === "yolo" && "All tools auto-approved in YOLO mode"}
          {config.mode === "ask" && "All tools require confirmation in ASK mode"}
          {config.mode === "granular" &&
            "Tools not in allow/deny list require confirmation"}
        </p>
      </div>
    </div>
  );
}
