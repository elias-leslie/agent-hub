'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Save } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  type CompactnessPolicy,
  fetchCompactnessPolicy,
  updateCompactnessPolicy,
} from '@/lib/api/compactness'
import { cn } from '@/lib/utils'

const DEFAULTS: CompactnessPolicy = {
  memory_max_chars: 280,
  memory_max_lines: 4,
  prompt_max_tokens: 350,
  prompt_max_lines: 80,
  max_sentence_words: 24,
  max_avg_sentence_words: 16,
  avg_sentence_min_words: 120,
  max_article_ratio_permille: 85,
  article_ratio_min_words: 80,
}

interface FieldDef {
  key: keyof CompactnessPolicy
  label: string
  hint: string
  default: number
  group: 'memory' | 'prompt' | 'sentence' | 'prose'
}

const FIELDS: FieldDef[] = [
  {
    key: 'memory_max_chars',
    label: 'Memory: max chars',
    hint: 'Above this, memory saves get a "long memory" warning.',
    default: 280,
    group: 'memory',
  },
  {
    key: 'memory_max_lines',
    label: 'Memory: max lines',
    hint: 'Above this, memory saves warn about multi-line bodies.',
    default: 4,
    group: 'memory',
  },
  {
    key: 'prompt_max_tokens',
    label: 'Prompt: max tokens',
    hint: 'Above this, prompt saves warn about hot-path cost.',
    default: 350,
    group: 'prompt',
  },
  {
    key: 'prompt_max_lines',
    label: 'Prompt: max lines',
    hint: 'Above this, prompts warn to collapse repeated examples.',
    default: 80,
    group: 'prompt',
  },
  {
    key: 'max_sentence_words',
    label: 'Sentence: max words',
    hint: 'Hard error when any single sentence exceeds this length.',
    default: 24,
    group: 'sentence',
  },
  {
    key: 'max_avg_sentence_words',
    label: 'Avg sentence: max words',
    hint: 'Hard error on overall verbosity (only fires past the prose-words threshold).',
    default: 16,
    group: 'sentence',
  },
  {
    key: 'avg_sentence_min_words',
    label: 'Avg sentence: min prose words to fire',
    hint: 'Avg-sentence rule only applies once content has at least this many words.',
    default: 120,
    group: 'sentence',
  },
  {
    key: 'max_article_ratio_permille',
    label: 'Article ratio: max ‰',
    hint: 'Hard error when articles (a/an/the) exceed this rate (permille; 85 = 8.5%).',
    default: 85,
    group: 'prose',
  },
  {
    key: 'article_ratio_min_words',
    label: 'Article ratio: min prose words to fire',
    hint: 'Article-ratio rule only applies once content has at least this many words.',
    default: 80,
    group: 'prose',
  },
]

const GROUPS: Array<{
  id: FieldDef['group']
  label: string
  description: string
}> = [
  {
    id: 'memory',
    label: 'Memory caps',
    description: 'Soft warnings that surface on memory saves.',
  },
  {
    id: 'prompt',
    label: 'Prompt caps',
    description: 'Soft warnings on prompt saves.',
  },
  {
    id: 'sentence',
    label: 'Sentence rules',
    description:
      'Hard errors that block saves when prose runs long. Loosen these when technical rules legitimately need a few more words.',
  },
  {
    id: 'prose',
    label: 'Prose density rules',
    description:
      'Hard errors flagging overly article-heavy content; tune the trigger thresholds here.',
  },
]

function inputValue(
  form: Partial<CompactnessPolicy>,
  key: keyof CompactnessPolicy,
) {
  const value = form[key]
  return value === undefined ? '' : String(value)
}

export default function CompactnessPolicyPage() {
  const queryClient = useQueryClient()
  const policyQuery = useQuery({
    queryKey: ['compactness', 'policy'],
    queryFn: fetchCompactnessPolicy,
  })
  const [form, setForm] = useState<Partial<CompactnessPolicy>>({})
  useEffect(() => {
    if (policyQuery.data) setForm(policyQuery.data)
  }, [policyQuery.data])

  const saveMutation = useMutation({
    mutationFn: () =>
      updateCompactnessPolicy(
        Object.fromEntries(
          Object.entries(form).filter(([, v]) => typeof v === 'number'),
        ),
      ),
    onSuccess: (data) => {
      setForm(data)
      queryClient.invalidateQueries({ queryKey: ['compactness', 'policy'] })
    },
  })

  const isLoading = policyQuery.isLoading
  const isPending = saveMutation.isPending

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <header className="space-y-1">
          <p className="text-xs uppercase tracking-[0.18em] text-slate-400 font-mono">
            Agent Hub / Compactness
          </p>
          <h1 className="text-2xl font-semibold">
            Compactness gate thresholds
          </h1>
          <p className="text-sm text-slate-400">
            Single source of truth for the strict-Caveman gate that runs on
            memory and prompt saves. Loosen sentence rules when technical
            content legitimately needs more breathing room. Edits take effect
            immediately for both the API and CLI.
          </p>
        </header>

        {isLoading ? (
          <div className="flex items-center gap-2 text-slate-400">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading policy…
          </div>
        ) : (
          <form
            onSubmit={(event) => {
              event.preventDefault()
              saveMutation.mutate()
            }}
            className="space-y-6"
          >
            {GROUPS.map((group) => (
              <section
                key={group.id}
                className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/40 p-4"
              >
                <div>
                  <h2 className="text-sm font-medium text-slate-200">
                    {group.label}
                  </h2>
                  <p className="text-xs text-slate-400">{group.description}</p>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  {FIELDS.filter((field) => field.group === group.id).map(
                    (field) => (
                      <label key={field.key} className="block space-y-1.5">
                        <span className="text-xs font-medium text-slate-300">
                          {field.label}
                        </span>
                        <input
                          type="number"
                          min={0}
                          inputMode="numeric"
                          value={inputValue(form, field.key)}
                          onChange={(event) => {
                            const raw = event.target.value
                            setForm((prev) => ({
                              ...prev,
                              [field.key]:
                                raw === ''
                                  ? undefined
                                  : Number.parseInt(raw, 10),
                            }))
                          }}
                          className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500/40 placeholder:text-slate-500"
                        />
                        <span className="text-[11px] text-slate-500">
                          {field.hint} Default: {field.default}.
                        </span>
                      </label>
                    ),
                  )}
                </div>
              </section>
            ))}

            <div className="flex items-center justify-between gap-3">
              <button
                type="button"
                onClick={() => setForm(DEFAULTS)}
                className="text-xs text-slate-400 hover:text-slate-200 underline-offset-2 hover:underline"
              >
                Reset to module defaults
              </button>
              <button
                type="submit"
                disabled={isPending}
                className={cn(
                  'inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                  'bg-emerald-600 hover:bg-emerald-700 text-white',
                  'disabled:opacity-50 disabled:cursor-not-allowed',
                )}
              >
                {isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Save className="w-4 h-4" />
                )}
                {isPending ? 'Saving…' : 'Save policy'}
              </button>
            </div>

            {saveMutation.isError ? (
              <div className="p-3 rounded-lg bg-red-900/20 border border-red-800 text-sm text-red-400">
                {saveMutation.error instanceof Error
                  ? saveMutation.error.message
                  : 'Failed to save policy'}
              </div>
            ) : null}
          </form>
        )}
      </div>
    </div>
  )
}
