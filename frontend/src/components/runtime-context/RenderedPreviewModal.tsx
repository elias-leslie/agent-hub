'use client'

import { Check, Copy, X } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'

interface Props {
  // Prompts + memories block (formatted via _render_blocks).
  rendered: string
  // project_index block, placed after authority-ordered operator context.
  projectIndex: string
  // Cross-session continuity, placed after the project index.
  continuity: string
  // tool_capabilities block, placed after continuity.
  toolCapabilities: string
  totalTokens: number
  budgetTokens: number
  budgetEnabled: boolean
  onClose: () => void
}

interface SectionDef {
  label: string
  hint: string
  body: string
}

export function RenderedPreviewModal({
  rendered,
  projectIndex,
  continuity,
  toolCapabilities,
  totalTokens,
  budgetTokens,
  budgetEnabled,
  onClose,
}: Props) {
  const [copied, setCopied] = useState(false)

  // Injection order matches the canonical delivery: authority-ordered operator
  // context first, then computed project, continuity, and capability blocks.
  const sections: SectionDef[] = [
    {
      label: 'Prompts + Memory',
      hint: 'Authority-ordered prompts and memory blocks',
      body: rendered,
    },
    {
      label: 'Project Index',
      hint: 'Computed at session start from .index.yaml',
      body: projectIndex,
    },
    {
      label: 'Continuity',
      hint: 'Recent activity scoped by project and branch',
      body: continuity,
    },
    {
      label: 'Tool Capabilities',
      hint: 'Computed at session start from CLI --help output',
      body: toolCapabilities,
    },
  ]
  const visible = sections.filter((s) => s.body && s.body.trim().length > 0)
  const fullRendered = visible.map((s) => s.body).join('\n')

  const handleCopy = async () => {
    if (!fullRendered) return
    await navigator.clipboard.writeText(fullRendered)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      data-testid="rendered-preview-modal"
    >
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative w-full max-w-4xl mx-4 max-h-[85vh] flex flex-col rounded-xl bg-slate-900 shadow-2xl border border-slate-800">
        <div className="flex items-center justify-between p-4 border-b border-slate-800">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">
              Rendered Boot Context
            </h2>
            <p className="text-xs text-slate-400 font-mono">
              Verbatim text injected into the agent's session start —{' '}
              {budgetEnabled
                ? `${totalTokens.toLocaleString()} tok · ${budgetTokens.toLocaleString()} tok telemetry target (not enforced)`
                : `${totalTokens.toLocaleString()} tok · budget telemetry off`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleCopy}
              disabled={!fullRendered}
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                copied
                  ? 'bg-emerald-700/30 text-emerald-300 border border-emerald-700'
                  : 'bg-slate-800 text-slate-200 border border-slate-700 hover:bg-slate-700',
              )}
              title="Copy the full concatenated boot context"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5" /> Copied
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" /> Copy
                </>
              )}
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close preview"
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 cursor-pointer"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>
        <div className="overflow-auto flex-1 p-4 space-y-4">
          {visible.length === 0 ? (
            <div className="text-xs text-slate-500 font-mono">
              (empty — no blocks rendered)
            </div>
          ) : (
            visible.map((section) => (
              <section
                key={section.label}
                data-testid={`preview-section:${section.label}`}
              >
                <header className="mb-1.5 flex items-baseline justify-between">
                  <h3 className="text-[11px] uppercase tracking-[0.18em] text-violet-300/90 font-semibold">
                    {section.label}
                  </h3>
                  <span className="text-[10px] text-slate-500 font-mono">
                    {section.hint}
                  </span>
                </header>
                <pre className="m-0 p-3 rounded-md bg-slate-950/60 border border-slate-800 text-xs leading-relaxed text-slate-200 font-mono whitespace-pre-wrap break-words">
                  {section.body}
                </pre>
              </section>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
