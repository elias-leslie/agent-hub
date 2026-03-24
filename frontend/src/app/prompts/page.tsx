"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Plus, Search, Trash2, Globe, FileText, Loader2, ScrollText } from "lucide-react";
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
    <div className="min-h-screen bg-slate-950">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      {/* Sticky header — matches dashboard/access-control pattern */}
      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 h-12 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ScrollText className="h-5 w-5 text-slate-400" />
            <h1 className="text-base font-semibold text-slate-100">
              Prompts
            </h1>
            <span className="text-xs font-mono text-slate-500 tabular-nums">
              {filtered.length} of {prompts?.length ?? 0}
            </span>
          </div>
          <button
            onClick={() => router.push("/prompts/new")}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-md bg-amber-600 text-white hover:bg-amber-500 transition-colors cursor-pointer"
          >
            <Plus className="h-3.5 w-3.5" />
            New Prompt
          </button>
        </div>
      </header>

      <main className="relative px-6 lg:px-8 py-5">
        {/* Filter bar */}
        <div className="flex items-center gap-3 mb-5 animate-fade-up">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
            <input
              type="text"
              placeholder="Search prompts..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-9 pr-3 py-2 text-sm rounded-lg border border-slate-700 bg-slate-900 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-amber-500/40 focus:border-amber-500/50 transition-colors"
            />
          </div>
          <select
            value={scopeFilter}
            onChange={(e) => setScopeFilter(e.target.value as FilterScope)}
            className="px-3 py-2 text-sm rounded-lg border border-slate-700 bg-slate-900 text-slate-100 focus:outline-none focus:ring-2 focus:ring-amber-500/40 focus:border-amber-500/50 cursor-pointer transition-colors"
          >
            <option value="all">All</option>
            <option value="global">Global Only</option>
            <option value="non-global">Non-Global</option>
          </select>
        </div>

        {/* Error state */}
        {isError && (
          <div className="p-3 rounded-lg bg-red-900/20 border border-red-800/50 text-sm text-red-400">
            Failed to load prompts. Please try again.
          </div>
        )}

        {/* Empty state */}
        {!isError && filtered.length === 0 && (
          <div className="text-center py-16 animate-fade-up">
            <FileText className="h-12 w-12 mx-auto mb-4 text-slate-600" />
            <p className="text-slate-400 mb-4">
              No prompts found
            </p>
            <button
              onClick={() => router.push("/prompts/new")}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg bg-amber-600 text-white hover:bg-amber-500 transition-colors cursor-pointer"
            >
              <Plus className="h-4 w-4" />
              Create Prompt
            </button>
          </div>
        )}

        {/* Prompts table */}
        {!isError && filtered.length > 0 && (
          <div className="overflow-x-auto rounded-xl border border-slate-800/80 bg-slate-900/60 backdrop-blur-sm animate-fade-up stagger-1">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800/80">
                  <th className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest text-left px-4 py-3">
                    Slug
                  </th>
                  <th className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest text-left px-4 py-3">
                    Name
                  </th>
                  <th className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest text-left px-4 py-3">
                    Description
                  </th>
                  <th className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest text-left px-4 py-3">
                    Scope
                  </th>
                  <th className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest text-left px-4 py-3">
                    Status
                  </th>
                  <th className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest text-left px-4 py-3">
                    Updated
                  </th>
                  <th className="text-[10px] font-semibold text-slate-400 uppercase tracking-widest text-right px-4 py-3">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((prompt: Prompt) => (
                  <tr
                    key={prompt.slug}
                    onClick={() => handleRowClick(prompt.slug)}
                    className="border-t border-slate-800/50 hover:bg-slate-800/40 cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-3">
                      <code className="text-xs font-mono text-slate-300 bg-slate-800 px-1.5 py-0.5 rounded">
                        {prompt.slug}
                      </code>
                    </td>
                    <td className="px-4 py-3 font-medium text-slate-100">
                      {prompt.name}
                    </td>
                    <td className="px-4 py-3 text-slate-400">
                      {truncate(prompt.description, 80)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {prompt.is_global && (
                          <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-amber-950/40 text-amber-400 inline-flex items-center gap-1">
                            <Globe className="h-3 w-3" />
                            Global
                          </span>
                        )}
                        {prompt.owner_agent_slug && (
                          <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-emerald-950/40 text-emerald-300 inline-flex items-center gap-1">
                            {prompt.owner_agent_slug}
                          </span>
                        )}
                        {prompt.deletion_locked && (
                          <span className="px-2 py-0.5 text-[10px] font-medium rounded-full bg-amber-950/40 text-amber-300 inline-flex items-center gap-1">
                            Locked
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn(
                        "px-2 py-0.5 text-[10px] font-medium rounded-full inline-flex items-center gap-1",
                        prompt.enabled
                          ? "bg-emerald-950/40 text-emerald-400"
                          : "bg-slate-800 text-slate-400",
                      )}>
                        {prompt.enabled ? "Enabled" : "Disabled"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-400 whitespace-nowrap font-mono text-xs">
                      {formatDate(prompt.updated_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={(e) => handleDelete(e, prompt.slug)}
                        disabled={prompt.deletion_locked}
                        className={cn(
                          "inline-flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors cursor-pointer",
                          prompt.deletion_locked &&
                            "cursor-not-allowed opacity-40 hover:bg-transparent hover:text-slate-400",
                          pendingDeleteSlug === prompt.slug
                            ? "bg-red-600 text-white hover:bg-red-700"
                            : "text-slate-400 hover:text-red-400 hover:bg-red-950/30",
                        )}
                        title={
                          prompt.deletion_locked
                            ? "Locked prompts cannot be deleted"
                            :
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
      </main>
    </div>
  );
}
