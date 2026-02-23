"use client";

import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  FolderLock,
  ChevronDown,
  Clock,
  Zap,
  ShieldOff,
  BookOpen,
  Pencil,
  Flame,
  Check,
  AlertCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/lib/formatters";
import {
  fetchProjectPermissions,
  updateProjectPermission,
  type ProjectPermission,
  type ProjectPermissionUpdate,
} from "@/lib/api";

// ─── Tier configuration ──────────────────────────────────────────────────────

const TIER_CONFIG = {
  off: {
    label: "Off",
    icon: ShieldOff,
    color: "text-slate-400",
    bg: "bg-slate-500/10",
    border: "border-l-slate-600",
    dot: "bg-slate-500",
    description: "No automation access",
  },
  read: {
    label: "Read",
    icon: BookOpen,
    color: "text-blue-400",
    bg: "bg-blue-500/10",
    border: "border-l-blue-500",
    dot: "bg-blue-500",
    description: "Read files, consult agents",
  },
  write: {
    label: "Write",
    icon: Pencil,
    color: "text-amber-400",
    bg: "bg-amber-500/10",
    border: "border-l-amber-500",
    dot: "bg-amber-500",
    description: "Read + write files, journals",
  },
  yolo: {
    label: "YOLO",
    icon: Flame,
    color: "text-emerald-400",
    bg: "bg-emerald-500/10",
    border: "border-l-emerald-500",
    dot: "bg-emerald-500",
    description: "Full access including bash",
  },
} as const;

type Tier = keyof typeof TIER_CONFIG;
const TIERS: Tier[] = ["off", "read", "write", "yolo"];

function formatHour(hour: number): string {
  if (hour === 0 || hour === 24) return "12:00 AM";
  if (hour === 12) return "12:00 PM";
  return hour < 12 ? `${hour}:00 AM` : `${hour - 12}:00 PM`;
}

// ─── Tier select dropdown ────────────────────────────────────────────────────

function TierSelect({
  value,
  onChange,
  disabled,
}: {
  value: Tier;
  onChange: (tier: Tier) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const config = TIER_CONFIG[value];
  const Icon = config.icon;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => !disabled && setOpen(!open)}
        disabled={disabled}
        className={cn(
          "flex items-center gap-2 px-3 py-1.5 rounded-md",
          "border border-slate-700/80 bg-slate-800/60",
          "hover:bg-slate-800 hover:border-slate-600",
          "transition-colors text-sm",
          "focus:outline-none focus:ring-1 focus:ring-amber-500/50",
          disabled && "opacity-50 cursor-not-allowed",
        )}
      >
        <span className={cn("h-2 w-2 rounded-full", config.dot)} />
        <Icon className={cn("h-3.5 w-3.5", config.color)} />
        <span className={cn("font-medium", config.color)}>{config.label}</span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 text-slate-500 transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-30"
            onClick={() => setOpen(false)}
            onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
          />
          <div className="absolute top-full left-0 mt-1 z-40 w-56 rounded-lg border border-slate-700 bg-slate-850 bg-slate-900 shadow-xl shadow-black/40 overflow-hidden">
            {TIERS.map((tier) => {
              const tc = TIER_CONFIG[tier];
              const TIcon = tc.icon;
              const selected = tier === value;
              return (
                <button
                  key={tier}
                  type="button"
                  onClick={() => {
                    onChange(tier);
                    setOpen(false);
                  }}
                  className={cn(
                    "w-full flex items-center gap-3 px-3 py-2.5 text-left",
                    "hover:bg-slate-800/80 transition-colors",
                    selected && "bg-slate-800/50",
                  )}
                >
                  <span className={cn("h-2 w-2 rounded-full flex-shrink-0", tc.dot)} />
                  <TIcon className={cn("h-4 w-4 flex-shrink-0", tc.color)} />
                  <div className="flex-1 min-w-0">
                    <p className={cn("text-sm font-medium", tc.color)}>
                      {tc.label}
                    </p>
                    <p className="text-[11px] text-slate-500">{tc.description}</p>
                  </div>
                  {selected && <Check className="h-4 w-4 text-amber-400 flex-shrink-0" />}
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

// ─── Toggle switch ───────────────────────────────────────────────────────────

function Toggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => !disabled && onChange(!checked)}
      disabled={disabled}
      className={cn(
        "relative inline-flex h-5 w-9 flex-shrink-0 rounded-full border-2 border-transparent",
        "transition-colors duration-200 ease-in-out",
        "focus:outline-none focus:ring-1 focus:ring-amber-500/50 focus:ring-offset-1 focus:ring-offset-slate-900",
        checked ? "bg-emerald-600" : "bg-slate-700",
        disabled && "opacity-40 cursor-not-allowed",
      )}
    >
      <span
        className={cn(
          "pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-sm",
          "transform transition-transform duration-200 ease-in-out",
          checked ? "translate-x-4" : "translate-x-0",
        )}
      />
    </button>
  );
}

// ─── Hour select ─────────────────────────────────────────────────────────────

function HourSelect({
  value,
  onChange,
  disabled,
}: {
  value: number;
  onChange: (v: number) => void;
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      disabled={disabled}
      className={cn(
        "bg-slate-800/60 border border-slate-700/80 rounded-md",
        "px-2 py-1 text-xs text-slate-300 font-mono",
        "focus:outline-none focus:ring-1 focus:ring-amber-500/50 focus:border-amber-500/50",
        "hover:border-slate-600 transition-colors",
        disabled && "opacity-40 cursor-not-allowed",
      )}
    >
      {Array.from({ length: 25 }, (_, i) => (
        <option key={i} value={i}>
          {formatHour(i)}
        </option>
      ))}
    </select>
  );
}

// ─── Save flash indicator ────────────────────────────────────────────────────

function SaveFlash({ saving, error }: { saving: boolean; error: boolean }) {
  if (!saving && !error) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium",
        "animate-pulse",
        error
          ? "bg-red-900/30 text-red-400"
          : "bg-emerald-900/30 text-emerald-400",
      )}
    >
      {error ? (
        <>
          <AlertCircle className="h-3 w-3" /> Error
        </>
      ) : (
        <>
          <Check className="h-3 w-3" /> Saved
        </>
      )}
    </span>
  );
}

// ─── Permission row ──────────────────────────────────────────────────────────

function PermissionRow({
  permission,
  onUpdate,
}: {
  permission: ProjectPermission;
  onUpdate: (projectId: string, update: ProjectPermissionUpdate) => void;
}) {
  const [savingField, setSavingField] = useState<string | null>(null);
  const [errorField, setErrorField] = useState<string | null>(null);
  const tier = permission.permission_tier as Tier;
  const tierConfig = TIER_CONFIG[tier];

  const handleUpdate = useCallback(
    (field: string, update: ProjectPermissionUpdate) => {
      setSavingField(field);
      setErrorField(null);
      onUpdate(permission.project_id, update);
      // Brief flash then clear
      setTimeout(() => setSavingField(null), 1200);
    },
    [permission.project_id, onUpdate],
  );

  return (
    <tr className="group hover:bg-slate-800/20 transition-colors">
      {/* Project */}
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "w-1 h-8 rounded-full flex-shrink-0",
              tierConfig.dot,
            )}
          />
          <div>
            <p className="text-sm font-semibold text-slate-100">
              {permission.project_id}
            </p>
            {permission.root_path && (
              <p className="text-[11px] text-slate-500 font-mono truncate max-w-[220px]">
                {permission.root_path}
              </p>
            )}
          </div>
        </div>
      </td>

      {/* Tier */}
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-2">
          <TierSelect
            value={tier}
            onChange={(newTier) =>
              handleUpdate("tier", { permission_tier: newTier })
            }
          />
          <SaveFlash
            saving={savingField === "tier"}
            error={errorField === "tier"}
          />
        </div>
      </td>

      {/* Auto Exec */}
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-2">
          <Toggle
            checked={permission.auto_exec_enabled}
            onChange={(v) =>
              handleUpdate("exec", { auto_exec_enabled: v })
            }
            disabled={tier === "off"}
            label={`Auto-exec for ${permission.project_id}`}
          />
          {tier === "off" && (
            <span className="text-[10px] text-slate-600">N/A</span>
          )}
          <SaveFlash
            saving={savingField === "exec"}
            error={errorField === "exec"}
          />
        </div>
      </td>

      {/* Execution Window */}
      <td className="px-4 py-3.5">
        {permission.auto_exec_enabled && tier !== "off" ? (
          <div className="flex items-center gap-1.5">
            <HourSelect
              value={permission.execution_start_hour}
              onChange={(v) =>
                handleUpdate("hours", { execution_start_hour: v })
              }
            />
            <span className="text-slate-600 text-xs">&ndash;</span>
            <HourSelect
              value={permission.execution_end_hour}
              onChange={(v) =>
                handleUpdate("hours", { execution_end_hour: v })
              }
            />
            <SaveFlash
              saving={savingField === "hours"}
              error={errorField === "hours"}
            />
          </div>
        ) : (
          <span className="text-xs text-slate-600">
            {tier === "off" ? "Disabled" : "Exec off"}
          </span>
        )}
      </td>

      {/* Updated */}
      <td className="px-4 py-3.5 text-sm text-slate-500">
        {formatRelativeTime(permission.updated_at)}
      </td>
    </tr>
  );
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function ProjectPermissionsPage() {
  const queryClient = useQueryClient();

  const { data: permissions, isLoading, error } = useQuery({
    queryKey: ["project-permissions"],
    queryFn: fetchProjectPermissions,
    refetchInterval: 30000,
  });

  const mutation = useMutation({
    mutationFn: ({
      projectId,
      update,
    }: {
      projectId: string;
      update: ProjectPermissionUpdate;
    }) => updateProjectPermission(projectId, update),
    onMutate: async ({ projectId, update }) => {
      await queryClient.cancelQueries({ queryKey: ["project-permissions"] });
      const previous = queryClient.getQueryData<ProjectPermission[]>([
        "project-permissions",
      ]);
      queryClient.setQueryData<ProjectPermission[]>(
        ["project-permissions"],
        (old) =>
          old?.map((p) =>
            p.project_id === projectId ? { ...p, ...update } : p,
          ),
      );
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["project-permissions"], context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["project-permissions"] });
    },
  });

  const handleUpdate = useCallback(
    (projectId: string, update: ProjectPermissionUpdate) => {
      mutation.mutate({ projectId, update });
    },
    [mutation],
  );

  // Stats
  const tierCounts = permissions?.reduce(
    (acc, p) => {
      const t = p.permission_tier as Tier;
      acc[t] = (acc[t] || 0) + 1;
      return acc;
    },
    {} as Record<Tier, number>,
  );

  const autoExecCount = permissions?.filter((p) => p.auto_exec_enabled).length ?? 0;

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      {/* Header */}
      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 h-12 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <FolderLock className="h-5 w-5 text-slate-400" />
            <h1 className="text-base font-semibold text-slate-100">
              Project Permissions
            </h1>
            {permissions && (
              <span className="text-xs text-slate-500">
                ({permissions.length})
              </span>
            )}
          </div>

          {/* Tier summary pills */}
          {tierCounts && (
            <div className="flex items-center gap-2">
              {TIERS.map((t) => {
                const count = tierCounts[t] || 0;
                if (count === 0) return null;
                const tc = TIER_CONFIG[t];
                return (
                  <span
                    key={t}
                    className={cn(
                      "flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium",
                      tc.bg,
                      tc.color,
                    )}
                  >
                    <span className={cn("h-1.5 w-1.5 rounded-full", tc.dot)} />
                    {count} {tc.label}
                  </span>
                );
              })}
              <span className="text-slate-600 text-[11px] mx-1">|</span>
              <span
                className={cn(
                  "flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium",
                  autoExecCount > 0
                    ? "bg-emerald-500/10 text-emerald-400"
                    : "bg-slate-500/10 text-slate-400",
                )}
              >
                <Zap className="h-3 w-3" />
                {autoExecCount} auto-exec
              </span>
            </div>
          )}
        </div>
      </header>

      <main className="relative px-6 lg:px-8 py-6">
        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-900/20 border border-red-800/50">
            <p className="text-sm text-red-400">
              Failed to load project permissions
            </p>
          </div>
        )}

        {isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-14 bg-slate-800/40 rounded animate-pulse" />
            ))}
          </div>
        ) : permissions?.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-slate-400">
            <FolderLock className="h-12 w-12 mb-4 opacity-40" />
            <p className="text-lg mb-1">No project permissions configured</p>
            <p className="text-xs text-slate-500">
              Run the migration to seed default permissions
            </p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-lg border border-slate-800/80">
            <table className="w-full">
              <thead className="bg-slate-800/50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Project
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Tier
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Auto Exec
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Execution Window
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Updated
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/50">
                {permissions?.map((p) => (
                  <PermissionRow
                    key={p.project_id}
                    permission={p}
                    onUpdate={handleUpdate}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>
    </div>
  );
}
