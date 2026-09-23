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
  const [selected, setSelected] = useState<string | null>(null)
  const queue = useQuery({
    queryKey: ['context-maintenance-history', context],
    queryFn: () =>
      contextRequest<ContextMaintenanceView>('/maintenance', {
        action: 'list',
        context,
        include_closed: true,
        include_background: true,
      }),
  })
  const inspection = useQuery({
    queryKey: ['context-maintenance-history-item', context, selected],
    enabled: Boolean(selected),
    queryFn: () =>
      contextRequest<{ item: ContextMaintenanceItem }>('/maintenance', {
        action: 'inspect',
        item_id: selected,
        context,
      }),
  })
  const items = queue.data?.items ?? []
  const active = inspection.data?.item
  return (
    <section className={styles.review} aria-label="Context review history">
      <div className={styles.actions}>
        <h2>Review history</h2>
        <button
          type="button"
          disabled={queue.isFetching}
          onClick={() => void queue.refetch()}
        >
          Refresh history
        </button>
      </div>
      <p>
        Automatic context maintenance is retired. Historical findings remain
        available for inspection.
      </p>
      {queue.isPending ? (
        <p>Loading review history…</p>
      ) : queue.error ? (
        <p role="alert" className={styles.error}>
          {queue.error.message}
        </p>
      ) : (
        <details>
          <summary>Historical findings ({items.length})</summary>
          {items.length === 0 && <p>No recorded findings in this context.</p>}
          {items.map((item) => (
            <article key={item.id} className={styles.finding}>
              <small>{item.state.replaceAll('_', ' ')}</small>
              <p>{item.summary}</p>
              <button type="button" onClick={() => setSelected(item.id)}>
                Inspect evidence
              </button>
            </article>
          ))}
        </details>
      )}
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
          <button type="button" onClick={() => setSelected(null)}>
            Close evidence
          </button>
        </article>
      )}
    </section>
  )
}
