"use client";

import { AlertTriangle, FileStack } from "lucide-react";

import type { AgentPreview, AgentPreviewSection } from "@/types/agent-preview";

interface PersonaPromptBudgetPanelProps {
  preview: AgentPreview | null;
  loading: boolean;
  error: string | null;
}

function toneForTokens(totalTokens: number | null | undefined) {
  if (typeof totalTokens !== "number") return "text-slate-300";
  if (totalTokens >= 14000) return "text-rose-300";
  if (totalTokens >= 8000) return "text-amber-300";
  return "text-emerald-300";
}

export function PersonaPromptBudgetPanel({
  preview,
  loading,
  error,
}: PersonaPromptBudgetPanelProps) {
  const totalTokens = preview?.memory_debug?.total_tokens;
  const sections = [...(preview?.sections ?? [])]
    .sort((left, right) => right.estimated_tokens - left.estimated_tokens)
    .slice(0, 5);

  return (
    <section
      data-testid="persona-prompt-budget-panel"
      className="rounded-[28px] border border-slate-800/70 bg-slate-900/80 p-4"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            <FileStack className="h-3.5 w-3.5 text-sky-300" />
            Prompt budget
          </div>
          <h3 className="mt-2 text-lg font-semibold text-slate-50">
            Keep runtime context lean enough to stay sharp.
          </h3>
          <p className="mt-2 text-sm leading-6 text-slate-400">
            Preview-derived estimate from prompt assembly. Treat as guidance until runtime publishes authoritative totals.
          </p>
        </div>
        <div className="text-right">
          <div className={`text-sm font-semibold ${toneForTokens(totalTokens)}`}>
            {typeof totalTokens === "number" ? `${totalTokens.toLocaleString()} tokens` : "Loading"}
          </div>
          <div className="mt-1 text-[11px] uppercase tracking-[0.18em] text-slate-500">
            Preview-derived estimate
          </div>
        </div>
      </div>

      {error ? (
        <div className="mt-4 rounded-2xl border border-rose-500/20 bg-rose-950/20 px-3 py-2 text-sm text-rose-200">
          {error}
        </div>
      ) : null}

      {!error && typeof totalTokens === "number" && totalTokens >= 14000 ? (
        <div className="mt-4 flex items-start gap-2 rounded-2xl border border-amber-500/20 bg-amber-950/20 px-3 py-2 text-sm text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          High prompt load. Trim runtime sections before this turns into slow, vague work.
        </div>
      ) : null}

      <div className="mt-4 space-y-2">
        {loading && !preview ? (
          <div className="rounded-2xl border border-slate-800/70 bg-slate-950/70 px-3 py-3 text-sm text-slate-400">
            Loading prompt preview…
          </div>
        ) : null}
        {sections.map((section: AgentPreviewSection) => (
          <div
            key={`${section.source_kind}:${section.source_id}:${section.content_hash}`}
            className="rounded-2xl border border-slate-800/70 bg-slate-950/70 px-3 py-2.5"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-slate-100">{section.label}</div>
                <div className="mt-1 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                  {section.source_kind}
                </div>
              </div>
              <div className="text-right text-sm text-slate-300">
                {section.estimated_tokens.toLocaleString()} tok
              </div>
            </div>
          </div>
        ))}
      </div>

      {preview?.memory_query ? (
        <div className="mt-3 rounded-2xl border border-slate-800/70 bg-slate-950/70 px-3 py-2 text-xs text-slate-400">
          Query: {preview.memory_query}
        </div>
      ) : null}
    </section>
  );
}
