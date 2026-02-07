"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Loader2, FileText } from "lucide-react";
import {
  fetchAgentPrompts,
  fetchPrompts,
  fetchRoles,
  assignPrompt,
  removeAssignment,
  AgentPromptAssignment,
  Prompt,
} from "@/lib/api/prompts";

interface PromptsTabProps {
  agentSlug: string;
}

export function PromptsTab({ agentSlug }: PromptsTabProps) {
  const queryClient = useQueryClient();
  const [showAssignForm, setShowAssignForm] = useState(false);
  const [selectedPromptSlug, setSelectedPromptSlug] = useState("");
  const [role, setRole] = useState("");
  const [customRole, setCustomRole] = useState("");
  const [priority, setPriority] = useState(0);

  const DEFAULT_ROLES = ["system", "autocode", "context", "guardrail"];

  const {
    data: assignments = [],
    isLoading: assignmentsLoading,
  } = useQuery<AgentPromptAssignment[]>({
    queryKey: ["agent-prompts", agentSlug],
    queryFn: () => fetchAgentPrompts(agentSlug),
  });

  const {
    data: allPrompts = [],
    isLoading: promptsLoading,
  } = useQuery<Prompt[]>({
    queryKey: ["prompts"],
    queryFn: () => fetchPrompts(),
    enabled: showAssignForm,
  });

  const { data: apiRoles = [] } = useQuery<string[]>({
    queryKey: ["prompt-roles"],
    queryFn: () => fetchRoles(),
    enabled: showAssignForm,
  });

  const roleOptions = [...new Set([...DEFAULT_ROLES, ...apiRoles])].sort();
  const effectiveRole = role === "__custom__" ? customRole : role;

  const assignedSlugs = new Set(assignments.map((a) => a.prompt.slug));
  const availablePrompts = allPrompts.filter((p) => !assignedSlugs.has(p.slug));

  const assignMutation = useMutation({
    mutationFn: (data: { prompt_slug: string; role: string; priority?: number }) =>
      assignPrompt(agentSlug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent-prompts", agentSlug] });
      queryClient.invalidateQueries({ queryKey: ["prompt-roles"] });
      setShowAssignForm(false);
      setSelectedPromptSlug("");
      setRole("");
      setCustomRole("");
      setPriority(0);
    },
  });

  const removeMutation = useMutation({
    mutationFn: (promptSlug: string) => removeAssignment(agentSlug, promptSlug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent-prompts", agentSlug] });
    },
  });

  const handleAssign = () => {
    if (!selectedPromptSlug || !effectiveRole) return;
    assignMutation.mutate({
      prompt_slug: selectedPromptSlug,
      role: effectiveRole,
      priority,
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          Prompt Assignments
        </h2>
        <button
          onClick={() => setShowAssignForm(!showAssignForm)}
          className="px-3 py-1.5 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
        >
          <span className="flex items-center gap-1.5">
            <Plus className="h-4 w-4" />
            Assign Prompt
          </span>
        </button>
      </div>

      {showAssignForm && (
        <div className="p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100 mb-4">
            Assign a Prompt
          </h3>
          <div className="space-y-4">
            <div>
              <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                Prompt
              </label>
              {promptsLoading ? (
                <div className="flex items-center gap-2 mt-1 text-sm text-slate-500">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading prompts...
                </div>
              ) : (
                <select
                  value={selectedPromptSlug}
                  onChange={(e) => setSelectedPromptSlug(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                >
                  <option value="">Select a prompt...</option>
                  {availablePrompts.map((p) => (
                    <option key={p.slug} value={p.slug}>
                      {p.name}
                    </option>
                  ))}
                </select>
              )}
            </div>

            <div>
              <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                Role
              </label>
              <select
                value={role}
                onChange={(e) => {
                  setRole(e.target.value);
                  if (e.target.value !== "__custom__") setCustomRole("");
                }}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
              >
                <option value="">Select a role...</option>
                {roleOptions.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
                <option value="__custom__">Other...</option>
              </select>
              {role === "__custom__" && (
                <input
                  type="text"
                  value={customRole}
                  onChange={(e) => setCustomRole(e.target.value)}
                  placeholder="Enter custom role"
                  className="w-full mt-2 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                />
              )}
            </div>

            <div>
              <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                Priority
              </label>
              <input
                type="number"
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
              />
            </div>

            <div className="flex items-center gap-2 pt-2">
              <button
                onClick={handleAssign}
                disabled={!selectedPromptSlug || !effectiveRole || assignMutation.isPending}
                className="px-3 py-1.5 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {assignMutation.isPending ? (
                  <span className="flex items-center gap-1.5">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Saving...
                  </span>
                ) : (
                  "Save"
                )}
              </button>
              <button
                onClick={() => {
                  setShowAssignForm(false);
                  setSelectedPromptSlug("");
                  setRole("");
                  setCustomRole("");
                  setPriority(0);
                }}
                className="px-3 py-1.5 text-sm font-medium rounded-lg border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
              >
                Cancel
              </button>
            </div>

            {assignMutation.isError && (
              <p className="text-sm text-red-500">
                Failed to assign prompt. Please try again.
              </p>
            )}
          </div>
        </div>
      )}

      {assignmentsLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
        </div>
      ) : assignments.length === 0 ? (
        <div className="text-center py-12 text-slate-500 dark:text-slate-400">
          <FileText className="h-8 w-8 mx-auto mb-3 opacity-50" />
          <p className="text-sm">No prompts assigned to this agent yet.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {assignments.map((assignment) => (
            <div
              key={assignment.prompt.slug}
              className="p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-slate-900 dark:text-slate-100">
                      {assignment.prompt.name}
                    </span>
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
                      {assignment.role}
                    </span>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      Priority: {assignment.priority}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
                    {assignment.prompt.content.slice(0, 100)}
                    {assignment.prompt.content.length > 100 ? "..." : ""}
                  </p>
                </div>
                <button
                  onClick={() => removeMutation.mutate(assignment.prompt.slug)}
                  disabled={removeMutation.isPending}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                  title="Remove assignment"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
