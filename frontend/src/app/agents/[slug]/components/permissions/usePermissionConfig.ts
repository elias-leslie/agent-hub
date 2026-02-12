import { useState } from "react";
import { PermissionConfig } from "../../types";
import { PermissionMode } from "./constants";

export function usePermissionConfig(
  config: PermissionConfig,
  updateConfig: (updates: Partial<PermissionConfig>) => void
) {
  const [newAllowTool, setNewAllowTool] = useState("");
  const [newDenyTool, setNewDenyTool] = useState("");

  const setMode = (mode: PermissionMode) => {
    updateConfig({ mode });
  };

  const addToAllowList = (tool: string) => {
    if (!tool.trim()) return;
    const newList = [...new Set([...config.allow_list, tool.trim()])];
    const newDenyList = config.deny_list.filter((t) => t !== tool.trim());
    updateConfig({ allow_list: newList, deny_list: newDenyList });
    setNewAllowTool("");
  };

  const addToDenyList = (tool: string) => {
    if (!tool.trim()) return;
    const newList = [...new Set([...config.deny_list, tool.trim()])];
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

  const getEffectivePermission = (
    toolName: string
  ): "allow" | "deny" | "ask" => {
    const toolPerm = config.tool_permissions[toolName];
    if (toolPerm) {
      if (!toolPerm.allowed) return "deny";
      if (toolPerm.requires_confirmation) return "ask";
      return "allow";
    }
    if (config.deny_list.includes(toolName)) return "deny";
    if (config.mode === "granular" && config.allow_list.includes(toolName)) {
      return "allow";
    }
    if (config.mode === "yolo") return "allow";
    if (config.mode === "ask") return "ask";
    return "ask";
  };

  return {
    newAllowTool,
    setNewAllowTool,
    newDenyTool,
    setNewDenyTool,
    setMode,
    addToAllowList,
    addToDenyList,
    removeFromAllowList,
    removeFromDenyList,
    getEffectivePermission,
  };
}
