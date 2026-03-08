"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Plus, Search, Trash2, Globe, FileText, Loader2 } from "lucide-react";
import { fetchPrompts, deletePrompt, Prompt } from "@/lib/api/prompts";
import { cn } from "@/lib/utils";

type FilterScope = "all" | "global" | "non-global";

export default function PromptsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState("");
  const [scopeFilter, setScopeFilter] = useState<FilterScope>("all");
  const [pendingDeleteSlug, setPendingDeleteSlug] = useState<string | null>(
    null,
  );

  const {
    data: prompts,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["prompts"],
    queryFn: () => fetchPrompts(),
  });

  const deleteMutation = useMutation({
    mutationFn: deletePrompt,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prompts"] });
      setPendingDeleteSlug(null);
    },
  });

  const filtered = (prompts ?? []).filter((p: Prompt) => {
    const matchesSearch =
      !search ||
      p.name.toLowerCase().includes(search.toLowerCase()) ||
      p.slug.toLowerCase().includes(search.toLowerCase()) ||
      (p.description ?? "").toLowerCase().includes(search.toLowerCase());

    const matchesScope =
      scopeFilter === "all" ||
      (scopeFilter === "global" && p.is_global) ||
      (scopeFilter === "non-global" && !p.is_global);

    return matchesSearch && matchesScope;
  });

  const handleRowClick = (slug: string) => {
    router.push(`/prompts/${slug}`);
  };

  const handleDelete = (e: React.MouseEvent, slug: string) => {
    e.stopPropagation();
    if (pendingDeleteSlug === slug) {
      deleteMutation.mutate(slug);
    } else {
      setPendingDeleteSlug(slug);
    }
  };

  const truncate = (text: string | null | undefined, max: number) => {
    if (!text) return "";
    return text.length > max ? text.slice(0, max) + "..." : text;
  };

  const formatDate = (dateStr: string | null | undefined) => {
    if (!dateStr) return "—";
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-100">
          Prompts
        </h1>
        <button
          onClick={() => router.push("/prompts/new")}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
        >
          <Plus className="h-4 w-4" />
          New Prompt
        </button>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 mb-6">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search prompts..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
          />
        </div>
        <select
          value={scopeFilter}
          onChange={(e) => setScopeFilter(e.target.value as FilterScope)}
          className="px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
        >
          <option value="all">All</option>
          <option value="global">Global Only</option>
          <option value="non-global">Non-Global</option>
        </select>
      </div>

      {/* Error state */}
      {isError && (
        <div className="text-center py-12 text-red-500 dark:text-red-400">
          Failed to load prompts. Please try again.
        </div>
      )}

      {/* Empty state */}
      {!isError && filtered.length === 0 && (
        <div className="text-center py-16">
          <FileText className="h-12 w-12 mx-auto mb-4 text-slate-300 dark:text-slate-600" />
          <p className="text-slate-500 dark:text-slate-400 mb-4">
            No prompts found
          </p>
          <button
            onClick={() => router.push("/prompts/new")}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
          >
            <Plus className="h-4 w-4" />
            Create Prompt
          </button>
        </div>
      )}

      {/* Prompts table */}
      {!isError && filtered.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-50 dark:bg-slate-900">
                <th className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider text-left px-4 py-3">
                  Slug
                </th>
                <th className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider text-left px-4 py-3">
                  Name
                </th>
                <th className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider text-left px-4 py-3">
                  Description
                </th>
                <th className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider text-left px-4 py-3">
                  Scope
                </th>
                <th className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider text-left px-4 py-3">
                  Status
                </th>
                <th className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider text-left px-4 py-3">
                  Updated
                </th>
                <th className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider text-right px-4 py-3">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((prompt: Prompt) => (
                <tr
                  key={prompt.slug}
                  onClick={() => handleRowClick(prompt.slug)}
                  className="border-t border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3">
                    <code className="text-xs font-mono text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">
                      {prompt.slug}
                    </code>
                  </td>
                  <td className="px-4 py-3 font-medium text-slate-900 dark:text-slate-100">
                    {prompt.name}
                  </td>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400">
                    {truncate(prompt.description, 80)}
                  </td>
                  <td className="px-4 py-3">
                    {prompt.is_global && (
                      <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-blue-100 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 inline-flex items-center gap-1">
                        <Globe className="h-3 w-3" />
                        Global
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={cn(
                      "px-2 py-0.5 text-[10px] font-medium rounded-full inline-flex items-center gap-1",
                      prompt.enabled
                        ? "bg-emerald-100 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400"
                        : "bg-slate-200 dark:bg-slate-800 text-slate-500 dark:text-slate-400",
                    )}>
                      {prompt.enabled ? "Enabled" : "Disabled"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                    {formatDate(prompt.updated_at)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={(e) => handleDelete(e, prompt.slug)}
                      className={cn(
                        "inline-flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors",
                        pendingDeleteSlug === prompt.slug
                          ? "bg-red-600 text-white hover:bg-red-700"
                          : "text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30",
                      )}
                      title={
                        pendingDeleteSlug === prompt.slug
                          ? "Click again to confirm"
                          : "Delete prompt"
                      }
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      {pendingDeleteSlug === prompt.slug && "Confirm"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
