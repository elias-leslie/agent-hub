import { CheckCircle2, Code } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Agent } from '../types'

interface GeneralTabProps {
  formData: Partial<Agent>
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void
}

export function GeneralTab({ formData, updateField }: GeneralTabProps) {
  return (
    <div className="space-y-6">
      <div className="section-header">
        <div>
          <p className="section-kicker">Identity</p>
          <h2 className="section-heading mt-2">General Settings</h2>
          <p className="section-copy mt-2 max-w-2xl">
            Set the operator-facing name, description, runtime availability, and
            whether this agent should be exposed to autonomous coding workflows.
          </p>
        </div>
      </div>

      <div className="section-card space-y-5">
        <div className="space-y-1.5">
          <label className="detail-label">Name</label>
          <input
            type="text"
            value={formData.name ?? ''}
            onChange={(e) => updateField('name', e.target.value)}
            className="control-input"
          />
        </div>

        <div className="space-y-1.5">
          <label className="detail-label">Description</label>
          <textarea
            value={formData.description ?? ''}
            onChange={(e) => updateField('description', e.target.value)}
            rows={3}
            className="control-input min-h-28 resize-y"
          />
        </div>

        <div className="grid gap-5 lg:grid-cols-2">
          <div className="detail-card space-y-3">
            <div>
              <p className="detail-label">Status</p>
              <p className="mt-2 text-sm text-slate-400">
                Decide whether this agent is available for routing and operator
                use.
              </p>
            </div>
            <div className="segmented-control">
              <button
                onClick={() => updateField('is_active', true)}
                className={cn(
                  'segmented-option',
                  formData.is_active
                    ? 'border-emerald-500/20 bg-emerald-500/12 text-emerald-100'
                    : 'hover:border-slate-700/80 hover:bg-slate-900/80 hover:text-slate-200',
                )}
              >
                <CheckCircle2 className="h-4 w-4" />
                Active
              </button>
              <button
                onClick={() => updateField('is_active', false)}
                className={cn(
                  'segmented-option',
                  !formData.is_active
                    ? 'border-slate-600 bg-slate-900/90 text-slate-100'
                    : 'hover:border-slate-700/80 hover:bg-slate-900/80 hover:text-slate-200',
                )}
              >
                Inactive
              </button>
            </div>
          </div>

          <div className="detail-card space-y-3">
            <div>
              <p className="detail-label">Autonomy Posture</p>
              <p className="mt-2 text-sm text-slate-400">
                Expose this agent to autonomous coding lanes when it should take
                implementation work.
              </p>
            </div>
            <div className="segmented-control">
              <button
                onClick={() => updateField('is_coding_agent', true)}
                className={cn(
                  'segmented-option',
                  formData.is_coding_agent
                    ? 'border-cyan-500/20 bg-cyan-500/12 text-cyan-100'
                    : 'hover:border-slate-700/80 hover:bg-slate-900/80 hover:text-slate-200',
                )}
              >
                <Code className="h-4 w-4" />
                Coding
              </button>
              <button
                onClick={() => updateField('is_coding_agent', false)}
                className={cn(
                  'segmented-option',
                  !formData.is_coding_agent
                    ? 'border-slate-600 bg-slate-900/90 text-slate-100'
                    : 'hover:border-slate-700/80 hover:bg-slate-900/80 hover:text-slate-200',
                )}
              >
                Non-coding
              </button>
            </div>
          </div>
        </div>

        <div className="detail-grid">
          <div className="detail-card">
            <p className="detail-label">Runtime State</p>
            <p className="detail-value">
              {formData.is_active
                ? 'Included in the live catalog and ready for dispatch.'
                : 'Hidden from active routing until re-enabled.'}
            </p>
          </div>
          <div className="detail-card">
            <p className="detail-label">Execution Role</p>
            <p className="detail-value">
              {formData.is_coding_agent
                ? 'Can take autonomous coding tasks and lane work.'
                : 'Reserved for analysis, review, or conversational work.'}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
