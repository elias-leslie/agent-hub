import type { PlanHistoryEntry } from '@/lib/api/workflow-runs'
import { planAuthor, planChangeText } from '../utils'

const ACTION_LABEL: Record<PlanHistoryEntry['action'], string> = {
  add_steps: 'Added steps',
  revise_step: 'Changed a step',
  remove_step: 'Removed a step',
  revise_run: 'Changed the run',
}

/** Compact record of plan revisions, newest first: who changed what, when, and from what to what. */
export function PlanHistory({ history }: { history: PlanHistoryEntry[] }) {
  if (history.length === 0) return null
  return (
    <details
      className="mb-4 rounded-lg border border-slate-800 bg-slate-950/70 p-3"
      data-testid="plan-history"
    >
      <summary className="cursor-pointer text-[12px] font-medium text-slate-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50">
        Plan history ({history.length}{' '}
        {history.length === 1 ? 'revision' : 'revisions'})
      </summary>
      <ol className="mt-2 space-y-2" aria-label="Plan history">
        {[...history].reverse().map((entry) => (
          <li key={entry.revision} className="text-[12px] text-slate-300">
            <p>
              <span className="font-mono tabular-nums text-slate-500">
                r{entry.revision}
              </span>{' '}
              <span className="font-medium">{ACTION_LABEL[entry.action]}</span>{' '}
              <span className="text-slate-500">
                by {planAuthor(entry.by)} at{' '}
                {new Date(entry.at * 1000).toLocaleString()}
              </span>
            </p>
            {entry.reason ? (
              <p className="text-slate-400">{entry.reason}</p>
            ) : null}
            <ul className="list-disc pl-5 text-slate-400">
              {entry.changes.map((change) => (
                <li
                  key={`${change.op}-${change.step ?? 'run'}`}
                  className="break-words"
                >
                  {planChangeText(change)}
                </li>
              ))}
              {entry.relinked && entry.relinked.length > 0 ? (
                <li>
                  now follows the step before the removed one:{' '}
                  {entry.relinked.join(', ')}
                </li>
              ) : null}
            </ul>
          </li>
        ))}
      </ol>
    </details>
  )
}
