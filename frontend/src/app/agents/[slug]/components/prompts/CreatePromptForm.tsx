"use client";

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus } from "lucide-react";

import {
  type AgentPromptAssignment,
  assignPrompt,
  createPrompt,
} from "@/lib/api/prompts";

function slugify(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

interface CreatePromptFormProps {
  agentSlug: string;
  orderedAssignments: AgentPromptAssignment[];
  onClose: () => void;
}

export function CreatePromptForm({
  agentSlug,
  orderedAssignments,
  onClose,
}: CreatePromptFormProps) {
  const queryClient = useQueryClient();
  const [newName, setNewName] = useState("");
  const [newSlug, setNewSlug] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newContent, setNewContent] = useState("");
  const [newRole, setNewRole] = useState("context");

  useEffect(() => {
    if (!newSlug) {
      setNewSlug(slugify(newName));
    }
  }, [newName, newSlug]);

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
      onClose();
    },
  });

  return (
    <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <h3 className="text-sm font-semibold text-slate-100">Create Prompt</h3>
      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-1.5">
          <span className="text-xs font-medium text-slate-400">Name</span>
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
          <span className="text-xs font-medium text-slate-400">Slug</span>
          <input
            value={newSlug}
            onChange={(event) => setNewSlug(slugify(event.target.value))}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
          />
        </label>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <label className="space-y-1.5">
          <span className="text-xs font-medium text-slate-400">Description</span>
          <textarea
            value={newDescription}
            onChange={(event) => setNewDescription(event.target.value)}
            rows={2}
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
          />
        </label>
        <label className="space-y-1.5">
          <span className="text-xs font-medium text-slate-400">Role</span>
          <input
            value={newRole}
            onChange={(event) => setNewRole(event.target.value)}
            list="prompt-role-options"
            className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none transition focus:border-slate-400 dark:border-slate-700 dark:bg-slate-950"
          />
        </label>
      </div>
      <label className="space-y-1.5">
        <span className="text-xs font-medium text-slate-400">Content</span>
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
          onClick={onClose}
          className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => createMutation.mutate()}
          disabled={!newName || !newSlug || !newContent || createMutation.isPending}
          className="inline-flex items-center gap-2 rounded-lg bg-amber-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-amber-500 disabled:opacity-50"
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
  );
}
