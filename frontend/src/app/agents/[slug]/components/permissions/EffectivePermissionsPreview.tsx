import { HelpCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { COMMON_TOOLS, PermissionMode } from "./constants";

interface EffectivePermissionsPreviewProps {
  mode: PermissionMode;
  getEffectivePermission: (toolName: string) => "allow" | "deny" | "ask";
}

export function EffectivePermissionsPreview({
  mode,
  getEffectivePermission,
}: EffectivePermissionsPreviewProps) {
  return (
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
        {mode === "yolo" && "All tools auto-approved in YOLO mode"}
        {mode === "ask" && "All tools require confirmation in ASK mode"}
        {mode === "granular" &&
          "Tools not in allow/deny list require confirmation"}
      </p>
    </div>
  );
}
