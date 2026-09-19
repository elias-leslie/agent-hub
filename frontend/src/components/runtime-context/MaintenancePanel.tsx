'use client'

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import {
  type ContextMaintenanceItem,
  type ContextMaintenanceView,
  type ContextSelection,
  type ContextSource,
  contextRequest,
} from '@/lib/api/context-management'
import styles from './context-manager.module.css'

export function MaintenancePanel({
  context,
  sources,
  onSelect,
}: {
  context: ContextSelection
  sources: ContextSource[]
  onSelect: (source: ContextSource) => void
}) {
  const [sessionId] = useState(() => `context-ui-${crypto.randomUUID()}`)
  const [selected, setSelected] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const selection = { ...context, session_id: sessionId }
  const queue = useQuery({
    queryKey: ['context-maintenance', context],
    queryFn: () =>
      contextRequest<ContextMaintenanceView>('/maintenance', {
        action: 'list',
        context: selection,
        include_closed: true,
      }),
  })
  const inspection = useQuery({
    queryKey: ['context-maintenance-item', context, selected, queue.data],
    enabled: Boolean(selected),
    queryFn: () =>
      contextRequest<{ item: ContextMaintenanceItem }>('/maintenance', {
        action: 'inspect',
        item_id: selected,
        context: selection,
      }),
  })
  const items = queue.data?.items ?? []
  const decisions = items.filter((item) => item.state === 'waiting_owner')
  const handoffs = items.filter(
    (item) => item.state === 'pending' && item.handoff_needed,
  )
  const active = inspection.data?.item
  async function act(action: 'answer' | 'dismiss' | 'recover' | 'resume') {
    if (!active || !reason.trim()) return
    setBusy(true)
    setError(null)
    try {
      await contextRequest('/maintenance', {
        action,
        item_id: active.id,
        expected_version: active.version,
        context: selection,
        reason,
        evidence: `Operator entered this ${action} in Runtime Context at ${new Date().toISOString()}`,
      })
      setReason('')
      await queue.refetch()
      await inspection.refetch()
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : 'Maintenance update failed',
      )
    } finally {
      setBusy(false)
    }
  }
  function select(item: ContextMaintenanceItem) {
    setSelected(item.id)
    setReason('')
    setError(null)
  }
  return (
    <section
      className={styles.review}
      aria-label="Background context maintenance"
    >
      <div className={styles.actions}>
        <h2>Background maintenance</h2>
        <button
          type="button"
          disabled={queue.isFetching}
          onClick={() => void queue.refetch()}
        >
          Refresh activity
        </button>
      </div>
      <p>
        The Memory Curator reviews changed context and handles routine upkeep.
        Relevant agents receive work that needs investigation. Only questions
        that need your judgment appear as decisions.
      </p>
      {queue.isPending ? (
        <p>Loading maintenance activity…</p>
      ) : queue.error ? (
        <p role="alert" className={styles.error}>
          Maintenance activity is unavailable: {queue.error.message}
        </p>
      ) : (
        <p>
          {decisions.length} owner decisions · {handoffs.length} agent handoffs
          ·{' '}
          {
            items.filter(
              (item) =>
                ['pending', 'claimed'].includes(item.state) &&
                !item.handoff_needed,
            ).length
          }{' '}
          background items
        </p>
      )}
      {decisions.map((item) => (
        <article key={item.id} className={styles.finding}>
          <h3>{item.decision.question}</h3>
          <p>{item.decision.recommendation}</p>
          <button type="button" onClick={() => select(item)}>
            Respond
          </button>
        </article>
      ))}
      <details>
        <summary>Activity and review history ({items.length})</summary>
        {items.length === 0 && <p>No maintenance findings in this context.</p>}
        {items.map((item) => (
          <article key={item.id} className={styles.finding}>
            <small>
              {item.state.replaceAll('_', ' ')} ·{' '}
              {item.claim_owner
                ? 'Claimed by an agent'
                : item.handoff_needed
                  ? 'Available to relevant agents'
                  : item.state === 'pending'
                    ? 'Background review'
                    : 'Recorded activity'}
            </small>
            <p>{item.summary}</p>
            <button type="button" onClick={() => select(item)}>
              Inspect evidence
            </button>
          </article>
        ))}
      </details>
      {selected && inspection.isPending && <p>Loading evidence…</p>}
      {inspection.error && (
        <p role="alert" className={styles.error}>
          {inspection.error.message}
        </p>
      )}
      {active && (
        <article className={styles.finding}>
          <h3>{active.summary}</h3>
          <p>{active.recommendation}</p>
          {active.detail?.finding?.uncertainty && (
            <p>Uncertainty: {active.detail.finding.uncertainty}</p>
          )}
          {active.detail?.failure && <p>{active.detail.failure}</p>}
          {active.detail?.background_reason && (
            <p>{active.detail.background_reason}</p>
          )}
          {Object.entries(active.detail?.finding?.passages ?? {}).map(
            ([key, passage]) => (
              <blockquote key={key}>{passage}</blockquote>
            ),
          )}
          <div className={styles.actions}>
            {sources
              .filter((source) => active.source_keys.includes(source.source_id))
              .map((source) => (
                <button
                  type="button"
                  key={`${source.source_type}:${source.source_id}`}
                  onClick={() => onSelect(source)}
                >
                  Open {source.name || source.source_id}
                </button>
              ))}
          </div>
          {active.decision.answer && (
            <p>Your recorded answer: {active.decision.answer}</p>
          )}
          {['pending', 'claimed', 'waiting_owner', 'deferred'].includes(
            active.state,
          ) && (
            <>
              <label>
                {active.state === 'waiting_owner'
                  ? 'Your answer'
                  : 'Reason for changing this item'}
                <textarea
                  rows={3}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
              {active.state === 'waiting_owner' && (
                <div className={styles.actions}>
                  {active.decision.options?.map((option) => (
                    <button
                      type="button"
                      key={option}
                      onClick={() => setReason(option)}
                    >
                      {option}
                    </button>
                  ))}
                </div>
              )}
              <div className={styles.actions}>
                {active.state === 'waiting_owner' && (
                  <button
                    type="button"
                    disabled={busy || !reason.trim()}
                    onClick={() => void act('answer')}
                  >
                    Save answer for the agent
                  </button>
                )}
                {active.claim_owner && (
                  <button
                    type="button"
                    disabled={busy || !reason.trim()}
                    onClick={() => void act('recover')}
                  >
                    Release an abandoned claim
                  </button>
                )}
                {active.state === 'deferred' && (
                  <button
                    type="button"
                    disabled={busy || !reason.trim()}
                    onClick={() => void act('resume')}
                  >
                    Resume review
                  </button>
                )}
                <button
                  type="button"
                  disabled={busy || !reason.trim()}
                  onClick={() => void act('dismiss')}
                >
                  Dismiss after assessment
                </button>
              </div>
            </>
          )}
          {error && (
            <p role="alert" className={styles.error}>
              {error}
            </p>
          )}
          <button type="button" onClick={() => setSelected(null)}>
            Close evidence
          </button>
        </article>
      )}
    </section>
  )
}
