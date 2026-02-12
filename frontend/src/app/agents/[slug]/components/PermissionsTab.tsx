import { Shield } from "lucide-react";
import { Agent, PermissionConfig } from "../types";
import { ModeSelector } from "./permissions/ModeSelector";
import { ToolListManager } from "./permissions/ToolListManager";
import { EffectivePermissionsPreview } from "./permissions/EffectivePermissionsPreview";
import { usePermissionConfig } from "./permissions/usePermissionConfig";

interface PermissionsTabProps {
  formData: Partial<Agent>;
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void;
}

export function PermissionsTab({ formData, updateField }: PermissionsTabProps) {
  const config: PermissionConfig = formData.tool_permissions || {
    mode: "yolo",
    tool_permissions: {},
    allow_list: [],
    deny_list: [],
  };

  const updateConfig = (updates: Partial<PermissionConfig>) => {
    updateField("tool_permissions", { ...config, ...updates });
  };

  const {
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
  } = usePermissionConfig(config, updateConfig);

  return (
    <div className="space-y-8">
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

      <ModeSelector currentMode={config.mode} onModeChange={setMode} />

      {config.mode === "granular" && (
        <ToolListManager
          allowList={config.allow_list}
          denyList={config.deny_list}
          newAllowTool={newAllowTool}
          newDenyTool={newDenyTool}
          onNewAllowToolChange={setNewAllowTool}
          onNewDenyToolChange={setNewDenyTool}
          onAddToAllowList={addToAllowList}
          onAddToDenyList={addToDenyList}
          onRemoveFromAllowList={removeFromAllowList}
          onRemoveFromDenyList={removeFromDenyList}
        />
      )}

      <EffectivePermissionsPreview
        mode={config.mode}
        getEffectivePermission={getEffectivePermission}
      />
    </div>
  );
}
