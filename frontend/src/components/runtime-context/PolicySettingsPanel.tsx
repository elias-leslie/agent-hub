'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Settings, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  fetchRuntimePolicy,
  updateRuntimePolicy,
} from '@/lib/api/runtime-context'
import { cn } from '@/lib/utils'
import styles from './runtime-context.module.css'

interface Props {
  profile: string
}

interface FormState {
  mandate: string
  guardrail: string
  reference: string
}

function toFormValue(value: number | null): string {
  if (value === null || value === undefined) return ''
  return String(value)
}

function parseFormValue(value: string): number | null {
  const trimmed = value.trim()
  if (trimmed === '') return null
  const parsed = Number.parseInt(trimmed, 10)
  if (Number.isNaN(parsed) || parsed < 0) return null
  return parsed
}

export function PolicySettingsPanel({ profile }: Props) {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const policyQuery = useQuery({
    queryKey: ['runtime-context', 'policy', profile],
    queryFn: () => fetchRuntimePolicy({ consumerProfile: profile }),
    enabled: open,
  })
  const [form, setForm] = useState<FormState>({
    mandate: '',
    guardrail: '',
    reference: '',
  })
  useEffect(() => {
    if (policyQuery.data) {
      setForm({
        mandate: toFormValue(policyQuery.data.mandate_limit),
        guardrail: toFormValue(policyQuery.data.guardrail_limit),
        reference: toFormValue(policyQuery.data.reference_limit),
      })
    }
  }, [policyQuery.data])
  const saveMutation = useMutation({
    mutationFn: () =>
      updateRuntimePolicy({
        consumerProfile: profile,
        payload: {
          mandate_limit: parseFormValue(form.mandate),
          guardrail_limit: parseFormValue(form.guardrail),
          reference_limit: parseFormValue(form.reference),
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['runtime-context', 'policy', profile],
      })
      queryClient.invalidateQueries({
        queryKey: ['runtime-context', 'preview'],
      })
      setOpen(false)
    },
  })

  return (
    <>
      <button
        type="button"
        className={styles.btn}
        onClick={() => setOpen(true)}
        title="Edit per-profile injection caps"
      >
        <Settings width={12} height={12} />
        Policy
      </button>
      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          data-testid="policy-settings-panel"
        >
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setOpen(false)}
          />
          <div className="relative w-full max-w-md mx-4 rounded-xl bg-slate-900 shadow-2xl border border-slate-800">
            <header className="flex items-center justify-between p-4 border-b border-slate-800">
              <div>
                <h2 className="text-lg font-semibold text-slate-100">
                  Policy caps · {profile}
                </h2>
                <p className="text-xs text-slate-400 font-mono">
                  Per-profile defaults. Leave blank for uncapped.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close policy panel"
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </header>
            <div className="p-4 space-y-3">
              {(['mandate', 'guardrail', 'reference'] as const).map((tier) => (
                <label key={tier} className="block">
                  <span className="text-xs uppercase tracking-[0.18em] text-slate-400 font-mono">
                    {tier} limit
                  </span>
                  <input
                    type="number"
                    min={0}
                    inputMode="numeric"
                    value={form[tier]}
                    onChange={(event) =>
                      setForm((prev) => ({
                        ...prev,
                        [tier]: event.target.value,
                      }))
                    }
                    placeholder="(uncapped)"
                    className="mt-1 w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/40 placeholder:text-slate-500"
                  />
                </label>
              ))}
              <p className="text-[11px] text-slate-500">
                0 = uncapped. Per-agent overrides can still tighten or loosen
                these defaults.
              </p>
            </div>
            <footer className="flex items-center justify-end gap-2 p-4 border-t border-slate-800">
              <button
                type="button"
                className={styles.btn}
                onClick={() => setOpen(false)}
              >
                Cancel
              </button>
              <button
                type="button"
                className={cn(styles.btn, styles.btnPrimary)}
                disabled={saveMutation.isPending}
                onClick={() => saveMutation.mutate()}
              >
                {saveMutation.isPending ? 'Saving…' : 'Save'}
              </button>
            </footer>
          </div>
        </div>
      ) : null}
    </>
  )
}
