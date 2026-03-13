"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileText,
  GripVertical,
  Loader2,
  Plus,
  Trash2,
  Unplug,
} from "lucide-react";

import type { AgentPreview, PreviewProjectOption, PreviewScenario, PreviewTaskType } from "../types";
import {
  AgentPromptAssignment,
  Prompt,
  assignPrompt,
  createPrompt,
  deletePrompt,
  fetchAgentPrompts,
  fetchOptionalPrompt,
  fetchPrompts,
  removeAssignment,
  updateAssignment,
  updatePrompt,
} from "@/lib/api/prompts";
import { fetchProjectConfigs } from "@/app/chat/hooks/useProjectContext";
import { AgentPreviewPanel } from "./AgentPreviewPanel";

interface PromptsTabProps {
  agentSlug: string;
  preview?: AgentPreview;
  previewFetching?: boolean;
  previewError?: string | null;
  showInlinePreview?: boolean;
  setShowInlinePreview?: (show: boolean) => void;
  previewMode?: PreviewTaskType;
  setPreviewMode?: (mode: PreviewTaskType) => void;
  previewScenario?: PreviewScenario;
  onPreviewScenarioChange?: (updates: Partial<PreviewScenario>) => void;
  refetchPreview?: () => void;
}

const PERSONA_WORKFLOW_PROMPT_SLUGS = [
  "persona-focus-harness",
  "persona-heartbeat-orchestrator",
  "persona-wake-guidance",
  "persona-onboarding-bootstrap",
  "persona-onboarding-continuation",
  "persona-onboarding-pending-approval",
  "persona-onboarding-review",
  "persona-evolution-guidelines",
];

const DEFAULT_ROLES = ["system", "autocode", "context", "guardrail"];

function slugify(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

interface PromptCardProps {
  agentSlug: string;
  assignment: AgentPromptAssignment;
  onPromptUpdated: () => void;
  onPromptDeleted: (slug: string) => void;
  onAssignmentRemoved: (slug: string) => void;
  draggable?: boolean;
  onDragStart?: (slug: string) => void;
  onDragOver?: (slug: string) => void;
  onDrop?: (slug: string) => void;
}

function PromptAssignmentCard({
  agentSlug,
  assignment,
  onPromptUpdated,
  onPromptDeleted,
  onAssignmentRemoved,
  draggable = false,
  onDragStart,
  onDragOver,
  onDrop,
}: PromptCardProps) {
  const prompt = assignment.prompt;
  const ownedByCurrentAgent = prompt.owner_agent_slug === agentSlug;
  const canDeletePrompt = ownedByCurrentAgent && !prompt.deletion_locked;
  const canRemoveAssignment = !ownedByCurrentAgent;
  const [expanded, setExpanded] = useState(false);
  const [name, setName] = useState(prompt.name);
  const [description, setDescription] = useState(prompt.description ?? "");
  const [content, setContent] = useState(prompt.content);
  const [enabled, setEnabled] = useState(prompt.enabled);
  const [role, setRole] = useState(assignment.role);

  useEffect(() => {
    setName(prompt.name);
    setDescription(prompt.description ?? "");
    setContent(prompt.content);
    setEnabled(prompt.enabled);
    setRole(assignment.role);
  }, [assignment.role, prompt.content, prompt.description, prompt.enabled, prompt.name]);

  const queryClient = useQueryClient();
  const saveMutation = useMutation({
    mutationFn: async () => {
      const promptChanged =
        name !== prompt.name ||
        description !== (prompt.description ?? "") ||
        content !== prompt.content ||
        enabled !== prompt.enabled;
      const assignmentChanged = role !== assignment.role;

      if (promptChanged) {
        await updatePrompt(prompt.slug, {
          name,
          description: description || undefined,
          content,
          enabled,
        });
      }
      if (assignmentChanged) {
        await updateAssignment(agentSlug, prompt.slug, { role });
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent-prompts", agentSlug] });
      queryClient.invalidateQueries({ queryKey: ["prompts"] });
      onPromptUpdated();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async () => deletePrompt(prompt.slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent-prompts", agentSlug] });
      queryClient.invalidateQueries({ queryKey: ["prompts"] });
      onPromptDeleted(prompt.slug);
    },
  });

  const removeMutation = useMutation({
    mutationFn: async () => removeAssignment(agentSlug, prompt.slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent-prompts", agentSlug] });
      onAssignmentRemoved(prompt.slug);
    },
  });

  const dirty =
    name !== prompt.name ||
    description !== (prompt.description ?? "") ||
    content !== prompt.content ||
    enabled !== prompt.enabled ||
    role !== assignment.role;

  return (
    <div
      draggable={draggable}
      onDragStart={() => onDragStart?.(prompt.slug)}
      onDragOver={(event) => {
        if (!draggable) return;
        event.preventDefault();
        onDragOver?.(prompt.slug);
      }}
      onDrop={() => onDrop?.(prompt.slug)}
      className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
    >
      <div className="flex items-center gap-2 px-4 py-3">
        {draggable ? (
          <span className="text-slate-400">
            <GripVertical className="h-4 w-4" />
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-slate-500" />
          ) : (
            <ChevronRight className="h-4 w-4 text-slate-500" />
          )}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                {prompt.name}
              </span>
              <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                {assignment.role}
              </span>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                p{assignment.priority}
              </span>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {prompt.prompt_type}
              </span>
              {prompt.deletion_locked ? (
                <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
                  locked
                </span>
              ) : null}
              {ownedByCurrentAgent ? (
                <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300">
                  owned
                </span>
              ) : null}
            </div>
            <p className="truncate text-xs text-slate-500 dark:text-slate-400">
              {prompt.slug}
            </p>
          </div>
        </button>
      </div>

      {expanded ? (
        <div className="space-y-4 border-t border-slate-200 px-4 py-4 dark:border-slate-800">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
                Name
              </span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
              />
            </label>
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
                Role
              </span>
              <input
                value={role}
                onChange={(event) => setRole(event.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
              />
            </label>
          </div>

          <label className="space-y-1.5">
            <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
              Description
            </span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={2}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
            />
          </label>

          <label className="space-y-1.5">
            <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
              Content
            </span>
            <textarea
              value={content}
              onChange={(event) => setContent(event.target.value)}
              rows={16}
              className="min-h-[260px] w-full rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
            />
          </label>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <label className="inline-flex items-center gap-2 text-xs text-slate-600 dark:text-slate-400">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
              />
              Enabled
            </label>
            <div className="flex flex-wrap items-center gap-2">
              {canRemoveAssignment ? (
                <button
                  type="button"
                  onClick={() => removeMutation.mutate()}
                  disabled={removeMutation.isPending}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-600 transition hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  <Unplug className="h-3.5 w-3.5" />
                  Remove Assignment
                </button>
              ) : null}
              {canDeletePrompt ? (
                <button
                  type="button"
                  onClick={() => deleteMutation.mutate()}
                  disabled={deleteMutation.isPending}
                  className="inline-flex items-center gap-1 rounded-lg border border-rose-200 px-3 py-2 text-xs font-medium text-rose-600 transition hover:bg-rose-50 disabled:opacity-50 dark:border-rose-900/60 dark:text-rose-300 dark:hover:bg-rose-950/30"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Delete Prompt
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => saveMutation.mutate()}
                disabled={!dirty || saveMutation.isPending}
                className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
              >
                {saveMutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                )}
                Save
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

interface LinkedPromptCardProps {
  prompt: Prompt;
  onUpdated: () => void;
}

function LinkedPromptCard({ prompt, onUpdated }: LinkedPromptCardProps) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [name, setName] = useState(prompt.name);
  const [description, setDescription] = useState(prompt.description ?? "");
  const [content, setContent] = useState(prompt.content);
  const [enabled, setEnabled] = useState(prompt.enabled);

  useEffect(() => {
    setName(prompt.name);
    setDescription(prompt.description ?? "");
    setContent(prompt.content);
    setEnabled(prompt.enabled);
  }, [prompt.content, prompt.description, prompt.enabled, prompt.name]);

  const saveMutation = useMutation({
    mutationFn: async () =>
      updatePrompt(prompt.slug, {
        name,
        description: description || undefined,
        content,
        enabled,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prompt", prompt.slug] });
      queryClient.invalidateQueries({ queryKey: ["persona-workflow-prompts"] });
      queryClient.invalidateQueries({ queryKey: ["prompts"] });
      onUpdated();
    },
  });

  const dirty =
    name !== prompt.name ||
    description !== (prompt.description ?? "") ||
    content !== prompt.content ||
    enabled !== prompt.enabled;

  return (
    <div className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left"
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4 text-slate-500" />
        ) : (
          <ChevronRight className="h-4 w-4 text-slate-500" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
              {prompt.name}
            </span>
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              linked
            </span>
          </div>
          <p className="truncate text-xs text-slate-500 dark:text-slate-400">{prompt.slug}</p>
        </div>
      </button>
      {expanded ? (
        <div className="space-y-4 border-t border-slate-200 px-4 py-4 dark:border-slate-800">
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-slate-600 dark:text-slate-400">Name</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
            />
          </label>
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
              Description
            </span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={2}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
            />
          </label>
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
              Content
            </span>
            <textarea
              value={content}
              onChange={(event) => setContent(event.target.value)}
              rows={14}
              className="min-h-[220px] w-full rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
            />
          </label>
          <div className="flex items-center justify-between gap-3">
            <label className="inline-flex items-center gap-2 text-xs text-slate-600 dark:text-slate-400">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(event) => setEnabled(event.target.checked)}
              />
              Enabled
            </label>
            <button
              type="button"
              onClick={() => saveMutation.mutate()}
              disabled={!dirty || saveMutation.isPending}
              className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-2 text-xs font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
            >
              {saveMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5" />
              )}
              Save
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function PromptsTab({
  agentSlug,
  preview,
  previewFetching = false,
  previewError,
  showInlinePreview = false,
  setShowInlinePreview,
  previewMode = "chat",
  setPreviewMode,
  previewScenario,
  onPreviewScenarioChange,
  refetchPreview,
}: PromptsTabProps) {
  const queryClient = useQueryClient();
  const [showAssignForm, setShowAssignForm] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [selectedPromptSlug, setSelectedPromptSlug] = useState("");
  const [assignRole, setAssignRole] = useState("context");
  const [newName, setNewName] = useState("");
  const [newSlug, setNewSlug] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newContent, setNewContent] = useState("");
  const [newRole, setNewRole] = useState("context");
  const [draggingSlug, setDraggingSlug] = useState<string | null>(null);

  const { data: assignments = [], isLoading: assignmentsLoading } = useQuery<AgentPromptAssignment[]>({
    queryKey: ["agent-prompts", agentSlug],
    queryFn: () => fetchAgentPrompts(agentSlug),
  });

  const { data: allPrompts = [] } = useQuery<Prompt[]>({
    queryKey: ["prompts"],
    queryFn: () => fetchPrompts(),
    enabled: showAssignForm,
  });

  const { data: personaWorkflowPrompts = [] } = useQuery<Prompt[]>({
    queryKey: ["persona-workflow-prompts"],
    enabled: agentSlug === "persona",
    queryFn: async () => {
      const prompts = await Promise.all(
        PERSONA_WORKFLOW_PROMPT_SLUGS.map((slug) => fetchOptionalPrompt(slug)),
      );
      return prompts.filter((prompt): prompt is Prompt => prompt !== null);
    },
  });
  const { data: previewProjects = [] } = useQuery<PreviewProjectOption[]>({
    queryKey: ["project-configs"],
    queryFn: fetchProjectConfigs,
  });

  const assignedSlugs = useMemo(
    () => new Set(assignments.map((assignment) => assignment.prompt.slug)),
    [assignments],
  );

  const availablePrompts = useMemo(
    () => allPrompts.filter((prompt) => !assignedSlugs.has(prompt.slug)),
    [allPrompts, assignedSlugs],
  );

  const orderedAssignments = useMemo(
    () => [...assignments].sort((left, right) => left.priority - right.priority),
    [assignments],
  );

  useEffect(() => {
    if (!newSlug) {
      setNewSlug(slugify(newName));
    }
  }, [newName, newSlug]);

  const assignMutation = useMutation({
    mutationFn: async (payload: { prompt_slug: string; role: string; priority: number }) =>
      assignPrompt(agentSlug, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent-prompts", agentSlug] });
      setSelectedPromptSlug("");
      setAssignRole("context");
      setShowAssignForm(false);
    },
  });

  const createMutation = useMutation({
    mutationFn: async () => {
      const prompt = await createPrompt({
        slug: newSlug,
        name: newName,
        description: newDescription || undefined,
        content: newContent,
        enabled: true,
      });
      const nextPriority =
        orderedAssignments.length === 0
          ? 0
          : orderedAssignments[orderedAssignments.length - 1].priority + 10;
      await assignPrompt(agentSlug, {
        prompt_slug: prompt.slug,
        role: newRole,
        priority: nextPriority,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prompts"] });
      queryClient.invalidateQueries({ queryKey: ["agent-prompts", agentSlug] });
      setNewName("");
      setNewSlug("");
      setNewDescription("");
      setNewContent("");
      setNewRole("context");
      setShowCreateForm(false);
    },
  });

  const reorderMutation = useMutation({
    mutationFn: async (nextAssignments: AgentPromptAssignment[]) => {
      await Promise.all(
        nextAssignments.map((assignment, index) =>
          updateAssignment(agentSlug, assignment.prompt.slug, {
            priority: index * 10,
          }),
        ),
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent-prompts", agentSlug] });
    },
  });

  const handleDrop = (targetSlug: string) => {
    if (!draggingSlug || draggingSlug === targetSlug) return;
    const current = [...orderedAssignments];
    const fromIndex = current.findIndex((assignment) => assignment.prompt.slug === draggingSlug);
    const toIndex = current.findIndex((assignment) => assignment.prompt.slug === targetSlug);
    if (fromIndex < 0 || toIndex < 0) return;
    const [moved] = current.splice(fromIndex, 1);
    current.splice(toIndex, 0, moved);
    setDraggingSlug(null);
    reorderMutation.mutate(current);
  };

  const canPreview = Boolean(setShowInlinePreview && setPreviewMode && refetchPreview);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Prompts</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Edit assigned prompt documents inline and reorder runtime prompt assignments.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setShowCreateForm((value) => !value);
              setShowAssignForm(false);
            }}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <Plus className="h-4 w-4" />
            New Prompt
          </button>
          <button
            type="button"
            onClick={() => {
              setShowAssignForm((value) => !value);
              setShowCreateForm(false);
            }}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-blue-700"
          >
            <Plus className="h-4 w-4" />
            Assign Existing
          </button>
        </div>
      </div>

      {showCreateForm ? (
        <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Create Prompt</h3>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">Name</span>
              <input
                value={newName}
                onChange={(event) => {
                  setNewName(event.target.value);
                  setNewSlug(slugify(event.target.value));
                }}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
              />
            </label>
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">Slug</span>
              <input
                value={newSlug}
                onChange={(event) => setNewSlug(slugify(event.target.value))}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
              />
            </label>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
                Description
              </span>
              <textarea
                value={newDescription}
                onChange={(event) => setNewDescription(event.target.value)}
                rows={2}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
              />
            </label>
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">Role</span>
              <input
                value={newRole}
                onChange={(event) => setNewRole(event.target.value)}
                list="prompt-role-options"
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
              />
            </label>
          </div>
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-slate-600 dark:text-slate-400">Content</span>
            <textarea
              value={newContent}
              onChange={(event) => setNewContent(event.target.value)}
              rows={12}
              className="min-h-[220px] w-full rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
            />
          </label>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowCreateForm(false)}
              className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => createMutation.mutate()}
              disabled={!newName || !newSlug || !newContent || createMutation.isPending}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
            >
              {createMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              Create and Assign
            </button>
          </div>
        </div>
      ) : null}

      {showAssignForm ? (
        <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Assign Existing Prompt</h3>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">Prompt</span>
              <select
                value={selectedPromptSlug}
                onChange={(event) => setSelectedPromptSlug(event.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
              >
                <option value="">Select a prompt...</option>
                {availablePrompts.map((prompt) => (
                  <option key={prompt.slug} value={prompt.slug}>
                    {prompt.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1.5">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400">Role</span>
              <input
                value={assignRole}
                onChange={(event) => setAssignRole(event.target.value)}
                list="prompt-role-options"
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
              />
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setShowAssignForm(false)}
              className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() =>
                assignMutation.mutate({
                  prompt_slug: selectedPromptSlug,
                  role: assignRole,
                  priority:
                    orderedAssignments.length === 0
                      ? 0
                      : orderedAssignments[orderedAssignments.length - 1].priority + 10,
                })
              }
              disabled={!selectedPromptSlug || !assignRole || assignMutation.isPending}
              className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:opacity-50"
            >
              {assignMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              Assign Prompt
            </button>
          </div>
        </div>
      ) : null}

      <datalist id="prompt-role-options">
        {DEFAULT_ROLES.map((role) => (
          <option key={role} value={role} />
        ))}
      </datalist>

      {canPreview ? (
        <AgentPreviewPanel
          preview={preview}
          previewFetching={previewFetching}
          previewError={previewError}
          previewMode={previewMode}
          onPreviewModeChange={(mode) => setPreviewMode?.(mode)}
          scenario={previewScenario ?? { projectId: "", phase: "", promptInput: "" }}
          onScenarioChange={(updates) => onPreviewScenarioChange?.(updates)}
          showPreview={showInlinePreview}
          onTogglePreview={() => setShowInlinePreview?.(!showInlinePreview)}
          onRefresh={() => refetchPreview?.()}
          projectOptions={previewProjects}
        />
      ) : null}

      <div className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
            Prompt Assignments
          </h3>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Drag to reorder the runtime prompt stack. Owned prompts stay under this agent; shared prompts can be detached.
          </p>
        </div>
        {assignmentsLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
          </div>
        ) : orderedAssignments.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-300 px-6 py-12 text-center text-slate-500 dark:border-slate-700 dark:text-slate-400">
            <FileText className="mx-auto mb-3 h-8 w-8 opacity-50" />
            No prompts assigned yet.
          </div>
        ) : (
          <div className="space-y-3">
            {orderedAssignments.map((assignment) => (
              <PromptAssignmentCard
                key={assignment.prompt.slug}
                agentSlug={agentSlug}
                assignment={assignment}
                draggable={reorderMutation.isPending === false}
                onDragStart={setDraggingSlug}
                onDragOver={() => undefined}
                onDrop={handleDrop}
                onPromptUpdated={() => undefined}
                onPromptDeleted={() => undefined}
                onAssignmentRemoved={() => undefined}
              />
            ))}
          </div>
        )}
      </div>

      {agentSlug === "persona" && personaWorkflowPrompts.length > 0 ? (
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Workflow Prompt Docs
            </h3>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              Jenny-specific workflow prompts that are used outside the ordered system prompt stack.
            </p>
          </div>
          <div className="space-y-3">
            {personaWorkflowPrompts.map((prompt) => (
              <LinkedPromptCard
                key={prompt.slug}
                prompt={prompt}
                onUpdated={() => undefined}
              />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
