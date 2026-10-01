'use client'

import { useQuery } from '@tanstack/react-query'
import type { Session } from '@/lib/api'
import { fetchNativeCaptureStatus } from '@/lib/api/native-capture'
import type { NativeEvidenceSummary } from '@/lib/api/native-evidence'

const labels: Record<string, string> = {
  app_server_registered: 'Managed App Server registered',
  rollout_only: 'Rollout recovery only',
  rollout: 'Rollout',
  shadow: 'Shadow observations',
  canonical_managed: 'Managed canonical projection',
  app_server: 'Managed App Server',
  local_verified: 'Locally verified',
  collector_attested: 'Collector attested',
  healthy: 'Healthy',
  degraded: 'Degraded',
  unsupported: 'Unsupported',
  disabled: 'Disabled',
  stale: 'Stale',
  partial: 'Partial',
  never_observed: 'Never observed',
  recent: 'Recently received',
  collector_reported_only: 'Collector reported; end-to-end delivery unverified',
  identity_attribution_unproven: 'Identity attribution is unproven',
  canonical_ordering_unproven: 'Canonical ordering is unproven',
}

function label(value: string | null | undefined) {
  return value ? (labels[value] ?? value.replaceAll('_', ' ')) : 'Unavailable'
}

export function NativeCapture({
  session,
  evidence,
  evidenceLoading,
  evidenceError,
  evidenceFetching,
  onRefreshEvidence,
  evidenceHasMore,
  evidenceLoadingMore,
  onLoadMoreEvidence,
}: {
  session: Session
  evidence?: NativeEvidenceSummary
  evidenceLoading?: boolean
  evidenceError?: boolean
  evidenceFetching?: boolean
  onRefreshEvidence?: () => void
  evidenceHasMore?: boolean
  evidenceLoadingMore?: boolean
  onLoadMoreEvidence?: () => void
}) {
  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['native-capture', session.id],
    queryFn: () => fetchNativeCaptureStatus(session.id),
    refetchInterval: session.status === 'active' ? 15000 : false,
  })

  return (
    <details className="shrink-0 border-b border-slate-800/60 bg-slate-900/50 px-4 py-3">
      <summary className="cursor-pointer text-sm text-slate-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
        Native capture ·{' '}
        {data
          ? label(data.capture_mode)
          : isLoading
            ? 'Loading'
            : 'Unavailable'}
        {error && data ? ' · refresh failed' : ''}
      </summary>
      <div className="mt-3 max-h-[50dvh] space-y-3 overflow-y-auto pr-1 text-xs text-slate-400">
        {isLoading && <p role="status">Loading capture health...</p>}
        {error && (
          <p role="status" className="text-amber-700 dark:text-amber-200">
            {data
              ? 'Capture health refresh failed. Showing the last loaded snapshot.'
              : 'Capture health is unavailable. Recorded session history remains available.'}
          </p>
        )}
        <button
          type="button"
          onClick={() => void refetch()}
          disabled={isFetching}
          className="rounded border border-slate-700 px-2 py-1 text-slate-200 hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-50"
        >
          {isFetching ? 'Refreshing...' : 'Refresh capture health'}
        </button>
        {data && (
          <>
            <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div>
                <dt>Requested model</dt>
                <dd className="mt-1 break-words text-slate-200">
                  {session.requested_model &&
                  session.requested_model !== 'codex/unknown'
                    ? session.requested_model
                    : 'Unknown'}
                </dd>
              </div>
              <div>
                <dt>Projection authority</dt>
                <dd className="mt-1 text-slate-200">
                  {label(data.projection_authority)}
                </dd>
              </div>
              <div>
                <dt>Promotion</dt>
                <dd className="mt-1 text-slate-200">
                  {label(data.promotion_state)}
                </dd>
              </div>
              <div>
                <dt>Configured model</dt>
                <dd className="mt-1 break-words text-slate-200">Unknown</dd>
              </div>
              <div>
                <dt>Observed delivered model</dt>
                <dd className="mt-1 break-words text-slate-200">
                  {data.observed_model || 'Unknown'}
                </dd>
              </div>
            </dl>
            <p>
              Promotion requested:{' '}
              {data.promotion_requested === undefined
                ? 'Unknown'
                : data.promotion_requested
                  ? 'Yes'
                  : 'No'}{' '}
              · Eligible:{' '}
              {data.promotion_eligible === undefined
                ? 'Unknown'
                : data.promotion_eligible
                  ? 'Yes'
                  : 'No'}
            </p>
            {!!data.promotion_blockers?.length && (
              <p className="text-amber-700 dark:text-amber-200">
                {data.promotion_blockers.map(label).join('. ')}.
              </p>
            )}
            <p>Delivery: {label(data.delivery_status)}</p>
            <p>
              Agent Hub owns canonical history and checkpoints. Source
              registration does not establish complete capture or delivery.
              Approval observations are audit records; existing approval
              authority remains in control.
            </p>
            {data.sources.length === 0 ? (
              <p>
                No native observation sources are registered. External sessions
                may have rollout history without managed capture.
              </p>
            ) : (
              <ul className="space-y-3">
                {data.sources.map((source) => (
                  <li
                    key={source.source_id}
                    className="rounded border border-slate-800 p-3"
                  >
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-slate-200">
                      <span>{label(source.kind)}</span>
                      <span>Session runtime {source.provider_version}</span>
                      <span>
                        {source.protocol_supported === undefined
                          ? 'Compatibility unknown'
                          : source.protocol_supported
                            ? 'Protocol compatible'
                            : 'Protocol incompatible; rollout fallback'}
                      </span>
                      <span>{label(source.capture_health?.state)}</span>
                      <span>{label(source.freshness)}</span>
                    </div>
                    <dl className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                      <div>
                        <dt>Checkpoint / retained receipts</dt>
                        <dd>
                          {source.committed_position} / {source.receipt_count}
                        </dd>
                      </div>
                      <div>
                        <dt>First missing position</dt>
                        <dd>
                          {source.first_missing_position ?? 'None recorded'}
                        </dd>
                      </div>
                      <div>
                        <dt>Capture gaps</dt>
                        <dd>
                          {source.capture_health?.capture_gaps ?? 'Unavailable'}
                        </dd>
                      </div>
                      <div>
                        <dt>Evidence issues</dt>
                        <dd>
                          {Object.values(source.issues).reduce(
                            (sum, count) => sum + count,
                            0,
                          )}
                        </dd>
                      </div>
                      <div>
                        <dt>Last receipt</dt>
                        <dd>{source.last_received_at ?? 'Unavailable'}</dd>
                      </div>
                      <div>
                        <dt>Conflict issues / unsupported receipts</dt>
                        <dd>
                          {source.dispositions
                            ? `${(source.issues.receipt_payload_conflict ?? 0) + (source.issues.entity_payload_conflict ?? 0) + (source.issues.entity_terminal_conflict ?? 0)} / ${source.dispositions.unsupported ?? 0}`
                            : 'Unavailable'}
                        </dd>
                      </div>
                    </dl>
                    <p className="mt-2 break-all">
                      {label(source.authenticity)} · Source {source.source_id}
                      {source.generation !== undefined
                        ? ` · Generation ${source.generation}`
                        : ''}
                      {source.projection_mode
                        ? ` · ${label(source.projection_mode)}`
                        : ''}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            <p>
              Installed Codex version and update or rollback validation are
              reported by the runtime owner in SummitFlow. Session runtime
              versions above describe their registered sources.
            </p>
          </>
        )}
        <div className="border-t border-slate-800/60 pt-3">
          <h3 className="font-medium text-slate-200">
            Provenance and approval audit
          </h3>
          {evidenceLoading && (
            <p className="mt-2" role="status">
              Loading evidence summary...
            </p>
          )}
          {evidenceError && (
            <p
              className="mt-2 text-amber-700 dark:text-amber-200"
              role="status"
            >
              {evidence
                ? 'Evidence refresh failed. Showing the last loaded summary.'
                : 'Evidence summary unavailable. Timeline history remains available.'}
            </p>
          )}
          {onRefreshEvidence && (
            <button
              type="button"
              onClick={onRefreshEvidence}
              disabled={evidenceFetching}
              className="mt-2 rounded border border-slate-700 px-2 py-1 text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-50"
            >
              {evidenceFetching ? 'Refreshing...' : 'Refresh evidence summary'}
            </button>
          )}
          {evidence && (
            <>
              <p className="mt-2">
                {evidence.commands.length} loaded canonical command entities.
                Open provenance on linked timeline events to inspect source
                receipts.
              </p>
              {evidenceHasMore && (
                <p className="mt-2">
                  More entities are available. Timeline provenance currently
                  covers loaded entities only.
                </p>
              )}
              {evidence.provenance_truncated && (
                <p className="mt-2 text-amber-700 dark:text-amber-200">
                  Receipt provenance is partial: the server capped at least one
                  page. Command and approval counts have separate coverage.
                </p>
              )}
              {evidenceHasMore && onLoadMoreEvidence && (
                <button
                  type="button"
                  onClick={onLoadMoreEvidence}
                  disabled={evidenceFetching || evidenceLoadingMore}
                  className="mt-2 rounded border border-slate-700 px-2 py-1 text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 disabled:opacity-50"
                >
                  {evidenceLoadingMore
                    ? 'Loading more...'
                    : 'Load more command provenance'}
                </button>
              )}
              <dl className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <div>
                  <dt>Inherited history receipts</dt>
                  <dd>{evidence.inherited_receipt_count}</dd>
                </div>
                <div>
                  <dt>Unresolved observations</dt>
                  <dd>{evidence.unresolved_receipt_count}</dd>
                </div>
                <div>
                  <dt>Validated approval requests / bound responses</dt>
                  <dd>
                    {evidence.approvals.validated_requests} /{' '}
                    {evidence.approvals.bound_responses}
                  </dd>
                </div>
                <div>
                  <dt>Cleared requests / unresolved bindings</dt>
                  <dd>
                    {evidence.approvals.cleared_requests} /{' '}
                    {evidence.approvals.unresolved}
                  </dd>
                </div>
              </dl>
              <p className="mt-2">
                Inherited receipts belong to earlier history and are separate
                from this session's execution. Approval counts describe capture
                and binding; they do not grant permission or replay a decision.
                Usage authority: {label(evidence.usage_authority)}.
              </p>
            </>
          )}
        </div>
      </div>
    </details>
  )
}
