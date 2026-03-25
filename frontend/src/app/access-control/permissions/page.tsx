"use client";

import { useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderLock, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchProjectPermissions,
  updateProjectPermission,
  type ProjectPermission,
  type ProjectPermissionUpdate,
} from "@/lib/api";
import { TIER_CONFIG, TIERS, type Tier } from "./_components/tier-config";
import { PermissionRow } from "./_components/PermissionRow";

// ─── Header summary pills ─────────────────────────────────────────────────────

function TierSummary({
  tierCounts,
  autoExecCount,
}: {
  tierCounts: Record<Tier, number>;
  autoExecCount: number;
}) {
  return (
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
  );
}

// ─── Permissions table ────────────────────────────────────────────────────────

function PermissionsTable({
  permissions,
  onUpdate,
}: {
  permissions: ProjectPermission[];
  onUpdate: (projectId: string, update: ProjectPermissionUpdate) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-slate-800/80">
      <table className="w-full">
        <thead className="bg-slate-800/50">
          <tr>
            {["Project", "Tier", "Auto Exec", "Execution Window", "Updated"].map(
              (col) => (
                <th
                  key={col}
                  className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400"
                >
                  {col}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/50">
          {permissions.map((p) => (
            <PermissionRow key={p.project_id} permission={p} onUpdate={onUpdate} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

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
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />

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
          {tierCounts && (
            <TierSummary tierCounts={tierCounts} autoExecCount={autoExecCount} />
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
              <div key={i} className="h-14 rounded-xl animate-shimmer" />
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
        ) : permissions ? (
          <PermissionsTable permissions={permissions} onUpdate={handleUpdate} />
        ) : null}
      </main>
    </div>
  );
}
