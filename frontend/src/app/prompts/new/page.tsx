"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Save,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Globe,
} from "lucide-react";
import { createPrompt } from "@/lib/api/prompts";
import { cn } from "@/lib/utils";

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

export default function PromptNewPage() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [description, setDescription] = useState("");
  const [isGlobal, setIsGlobal] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [autoSlug, setAutoSlug] = useState(true);

  const handleNameChange = (value: string) => {
    setName(value);
    if (autoSlug) {
      setSlug(slugify(value));
    }
  };

  const handleSlugChange = (value: string) => {
    setAutoSlug(false);
    setSlug(slugify(value));
  };

  const createMutation = useMutation({
    mutationFn: () =>
      createPrompt({
        slug,
        name,
        content,
        description: description || undefined,
        is_global: isGlobal,
        enabled,
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["prompts"] });
      router.push(`/prompts/${data.slug}`);
    },
  });

  return (
    <div className="page-shell">
      {/* Toast notifications */}
      {createMutation.isSuccess && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-950/40 border border-emerald-800 text-emerald-400 text-sm shadow-lg">
          <CheckCircle2 className="h-4 w-4" />
          Prompt created successfully
        </div>
      )}
      {createMutation.isError && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-2 px-4 py-2 rounded-lg bg-red-950/40 border border-red-800 text-red-400 text-sm shadow-lg">
          <AlertCircle className="h-4 w-4" />
          Failed to create prompt
        </div>
      )}

      {/* Header */}
      <div className="border-b border-slate-800 bg-slate-900 px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push("/prompts")}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-300 hover:bg-slate-800 transition-colors"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <h1 className="text-lg font-semibold text-slate-100">
              New Prompt
            </h1>
          </div>
          <button
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending || !slug || !name || !content}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-amber-500 text-slate-950 hover:bg-amber-400 disabled:opacity-50 transition-colors"
          >
            {createMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <span className="flex items-center gap-2">
                <Save className="h-4 w-4" />
                Create
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Form */}
      <div className="max-w-4xl mx-auto px-6 py-8">
        <div className="space-y-6">
          {/* Name */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="My Prompt"
              className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40"
            />
          </div>

          {/* Slug (editable, auto-generated from name) */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Slug
            </label>
            <input
              type="text"
              value={slug}
              onChange={(e) => handleSlugChange(e.target.value)}
              placeholder="my-prompt"
              className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-amber-500/40"
            />
            {autoSlug && name && (
              <p className="text-xs text-slate-400">
                Auto-generated from name
              </p>
            )}
          </div>

          {/* Content */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Content
            </label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Enter prompt content..."
              style={{ minHeight: "300px" }}
              className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-amber-500/40 resize-y"
            />
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              placeholder="Optional description..."
              className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 resize-y"
            />
          </div>

          {/* Is Global toggle */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Scope & Status
            </label>
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={() => setIsGlobal(true)}
                className={cn(
                  "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors",
                  isGlobal
                    ? "bg-amber-950/40 border-amber-800 text-amber-500"
                    : "border-slate-700 text-slate-400 hover:bg-slate-50",
                )}
              >
                <Globe className="h-4 w-4" />
                Global
              </button>
              <button
                onClick={() => setIsGlobal(false)}
                className={cn(
                  "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors",
                  !isGlobal
                    ? "bg-slate-800 border-slate-600 text-slate-700"
                    : "border-slate-700 text-slate-400 hover:bg-slate-50",
                )}
              >
                Non-Global
              </button>
              <button
                onClick={() => setEnabled(!enabled)}
                className={cn(
                  "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors",
                  enabled
                    ? "bg-emerald-950/40 border-emerald-800 text-emerald-600"
                    : "bg-slate-800 border-slate-600 text-slate-400",
                )}
              >
                {enabled ? "Enabled" : "Disabled"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
