'use client'

import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { fetchAgents } from '@/lib/api/agents'
import {
  type ContextDraft,
  type ContextInventory,
  type ContextPolicy,
  type ContextRecord,
  type ContextReview,
  type ContextSelection,
  type ContextSource,
  contextRequest,
  type PlacementEdit,
  type SourceEdit,
} from '@/lib/api/context-management'
import { fetchProjectCatalog } from '@/lib/api/project-permissions'
import { getModels } from '@/lib/models'
import { ContextInspector } from './ContextInspector'
import styles from './context-manager.module.css'
import { MaintenancePanel } from './MaintenancePanel'
import { PolicyModal } from './PolicyModal'

const sourceKey = (source: { source_type: string; source_id: string }) =>
  `${source.source_type}:${source.source_id}`
const list = (value: string) =>
  value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)

export function ContextManager() {
  const [context, setContext] = useState<ContextSelection>({
    consumer_surface: 'codex',
    consumer_profile: 'agent_startup',
    project_id: null,
    capabilities: ['bash'],
    workflow_ids: [],
    requested_source_ids: [],
    query: 'startup context',
  })
  const [edits, setEdits] = useState<Record<string, SourceEdit>>({})
  const [placements, setPlacements] = useState<Record<string, PlacementEdit>>(
    {},
  )
  const [preview, setPreview] = useState<ContextInventory | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [checked, setChecked] = useState<string[]>([])
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState('all')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [showRendered, setShowRendered] = useState(false)
  const [policyOpen, setPolicyOpen] = useState(false)
  const [review, setReview] = useState<ContextReview | null>(null)
  const [reviewMode, setReviewMode] = useState<
    'deterministic' | 'curator' | 'jev'
  >('deterministic')
  const [reviewModel, setReviewModel] = useState('')
  const [reason, setReason] = useState('Operator context edit')
  const [nativeText, setNativeText] = useState('')
  const [proposalId, setProposalId] = useState<string | undefined>()
  const [bulkScope, setBulkScope] = useState<ContextPolicy['scope']>('project')
  const [bulkTarget, setBulkTarget] = useState('')
  const [bulkActivation, setBulkActivation] =
    useState<ContextPolicy['activation']>('always')
  const models = useQuery({
    queryKey: ['context-typed-models'],
    queryFn: getModels,
  })
  const typedModels = (models.data ?? []).filter(
    (model) => model.capabilities.supports_typed_judgment,
  )
  const effectiveReviewModel = reviewModel || typedModels[0]?.id || ''
  const projects = useQuery({
    queryKey: ['context-projects'],
    queryFn: fetchProjectCatalog,
  })
  const agents = useQuery({
    queryKey: ['context-agents'],
    queryFn: () => fetchAgents(false),
  })
  const query = useQuery({
    queryKey: ['context-manager', context],
    queryFn: () => contextRequest<ContextInventory>('/inventory', context),
  })
  const sources = [...(preview?.sources ?? query.data?.sources ?? [])].sort(
    (a, b) => {
      const rank: Record<string, number> = {
        included: 0,
        indexed: 1,
        'eligible, not selected': 2,
        'excluded here': 3,
      }
      return (
        (rank[a.state] ?? 4) - (rank[b.state] ?? 4) ||
        a.name.localeCompare(b.name)
      )
    },
  )
  const originalSources = query.data?.sources ?? []
  const active = sources.find((source) => sourceKey(source) === selected)
  const draftActive = active ? edits[sourceKey(active)] : undefined
  const changes = Object.keys(edits).length + Object.keys(placements).length
  const rows = useMemo(
    () =>
      sources.filter((source) => {
        const text =
          `${source.name} ${source.source_id} ${source.content} ${source.policy?.scope}`.toLowerCase()
        return (
          text.includes(search.toLowerCase()) &&
          (filter === 'all' ||
            source.source_type === filter ||
            source.state === filter ||
            (filter === 'review available' &&
              source.review_status?.includes('available')) ||
            (filter === 'stale review' &&
              source.review_status === 'stale review') ||
            (filter === 'changed' &&
              Boolean(
                edits[sourceKey(source)] || placements[sourceKey(source)],
              )))
        )
      }),
    [sources, search, filter, edits, placements],
  )
  const history = useQuery({
    queryKey: [
      'context-history',
      active?.source_id,
      query.data?.delivery.delivery_id,
    ],
    enabled: Boolean(active),
    queryFn: () =>
      contextRequest<ContextRecord[]>(
        `/history?source_id=${encodeURIComponent(active?.source_id ?? '')}`,
      ),
  })
  const editWarnings = Object.values(edits).flatMap((edit) => {
    const warnings: string[] = []
    if (edit.policy?.scope === 'project' && !edit.policy.targets.length)
      warnings.push(`${edit.source_id}: choose a project target.`)
    if (edit.policy?.required && edit.policy.activation === 'on_demand')
      warnings.push(
        `${edit.source_id}: required rules must be upfront or triggered. Choose advisory for on-demand references.`,
      )
    if (
      edit.content &&
      originalSources.some(
        (source) =>
          source.source_id !== edit.source_id &&
          source.content.trim() === edit.content?.trim(),
      )
    )
      warnings.push(
        `${edit.source_id}: this text duplicates another source. Review its scope before saving.`,
      )
    return warnings
  })
  const dirtyPlacement = Object.keys(placements).length > 0
  const draft: ContextDraft = {
    context,
    edits: Object.values(edits),
    placements: Object.values(placements),
    expected_placement_revision: query.data?.placement_revision ?? '',
    reason,
    proposal_id: proposalId,
  }

  function changeContext(update: Partial<ContextSelection>) {
    setContext((current) => ({ ...current, ...update }))
    setPreview(null)
    setReview(null)
  }
  function stage(source: ContextSource, change: Partial<SourceEdit>) {
    if (source.source_type === 'computed') return
    const original =
      originalSources.find((item) => sourceKey(item) === sourceKey(source)) ??
      source
    setEdits((current) => ({
      ...current,
      [sourceKey(source)]: {
        ...current[sourceKey(source)],
        source_type: source.source_type as 'prompt' | 'memory',
        source_id: source.source_id,
        expected_revision: original.revision,
        ...change,
      },
    }))
    setPreview(null)
  }
  function place(source: ContextSource, mode: PlacementEdit['mode']) {
    if (source.source_type === 'computed') return
    setPlacements((current) => ({
      ...current,
      [sourceKey(source)]: {
        source_type: source.source_type as 'prompt' | 'memory',
        source_id: source.source_id,
        mode,
      },
    }))
    setPreview(null)
  }
  async function perform(work: () => Promise<void>) {
    setError(null)
    setNotice(null)
    setBusy(true)
    try {
      await work()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Context request failed')
    } finally {
      setBusy(false)
    }
  }
  async function previewChanges() {
    await perform(async () => {
      setPreview(await contextRequest<ContextInventory>('/preview', draft))
    })
  }
  async function saveChanges() {
    await perform(async () => {
      await contextRequest<ContextInventory>('/save', draft)
      setEdits({})
      setPlacements({})
      setPreview(null)
      setProposalId(undefined)
      await query.refetch()
      await history.refetch()
      setNotice(
        'Saved. Changes apply to future context generation. Existing native session messages cannot be retracted.',
      )
    })
  }
  async function reviewContext(dryRun: boolean) {
    await perform(async () => {
      setReview(
        await contextRequest<ContextReview>('/review', {
          context,
          source_ids: checked
            .map(
              (key) =>
                sources.find((source) => sourceKey(source) === key)?.source_id,
            )
            .filter(Boolean),
          mode: reviewMode,
          dry_run: dryRun,
          native_snapshots: nativeText
            ? [
                {
                  name: 'operator-supplied-native-snapshot',
                  content: nativeText,
                  revision: 'operator-supplied',
                  surface: context.consumer_surface,
                },
              ]
            : [],
          model_id: effectiveReviewModel || null,
        }),
      )
    })
  }
  const delivery = preview?.delivery ?? query.data?.delivery
  const bulkSources = sources.filter(
    (source) =>
      checked.includes(sourceKey(source)) &&
      source.policy &&
      source.owner_agent_id === null,
  )

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1>Runtime context</h1>
          <p>
            Manage when instructions and memory become available. Preview uses
            the same assembler as delivery.
          </p>
        </div>
        <button
          type="button"
          disabled={changes > 0}
          onClick={() => setPolicyOpen(true)}
        >
          Reference selection policy
        </button>
        <button
          type="button"
          disabled={busy || query.isFetching}
          onClick={() =>
            void perform(async () => {
              setPreview(null)
              await query.refetch()
            })
          }
        >
          Refresh
        </button>
      </header>
      <MaintenancePanel
        context={context}
        sources={originalSources}
        onSelect={(source) => setSelected(sourceKey(source))}
      />
      <PolicyModal
        profile={context.consumer_profile}
        isOpen={policyOpen}
        onClose={() => {
          setPolicyOpen(false)
          setPreview(null)
          void query.refetch()
        }}
      />
      <section className={styles.previewControls} aria-label="Preview context">
        <strong>Preview as</strong>
        <label>
          Project
          <select
            aria-label="Preview project"
            value={context.project_id ?? ''}
            disabled={dirtyPlacement}
            onChange={(event) =>
              changeContext({ project_id: event.target.value || null })
            }
          >
            <option value="">No project (global)</option>
            {projects.data?.map((project) => (
              <option key={project.project_id} value={project.project_id}>
                {project.label || project.project_id}
              </option>
            ))}
          </select>
        </label>
        <label>
          Consumer
          <select
            value={context.consumer_surface}
            disabled={dirtyPlacement}
            onChange={(event) =>
              changeContext({
                consumer_surface: event.target.value,
                capabilities: ['codex', 'claude_code', 'pi'].includes(
                  event.target.value,
                )
                  ? ['bash']
                  : [],
              })
            }
          >
            <option value="codex">Codex</option>
            <option value="claude_code">Claude Code</option>
            <option value="pi">Pi</option>
            <option value="agent_runtime">Internal agent</option>
            <option value="mcp">MCP</option>
          </select>
        </label>
        <label>
          Profile
          <select
            value={context.consumer_profile}
            disabled={dirtyPlacement}
            onChange={(event) =>
              changeContext({ consumer_profile: event.target.value })
            }
          >
            {(query.data?.profiles ?? [context.consumer_profile]).map(
              (profile) => (
                <option key={profile} value={profile}>
                  {profile.replaceAll('_', ' ')}
                </option>
              ),
            )}
          </select>
        </label>
        <label>
          Task type
          <input
            value={context.task_type ?? ''}
            placeholder="Any"
            onChange={(event) =>
              changeContext({ task_type: event.target.value || null })
            }
          />
        </label>
        <label>
          Phase
          <input
            value={context.phase ?? ''}
            placeholder="Any"
            onChange={(event) =>
              changeContext({ phase: event.target.value || null })
            }
          />
        </label>
        <label>
          Active workflows
          <input
            value={context.workflow_ids.join(', ')}
            placeholder="None"
            onChange={(event) =>
              changeContext({ workflow_ids: list(event.target.value) })
            }
          />
        </label>
        <details>
          <summary>Session and retrieval</summary>
          <div className={styles.previewControls}>
            <label>
              Session
              <input
                value={context.session_id ?? ''}
                placeholder="Optional session ID"
                onChange={(event) =>
                  changeContext({ session_id: event.target.value || null })
                }
              />
            </label>
            <label>
              Agent
              <input
                list="context-agents"
                value={context.agent_slug ?? ''}
                placeholder="Optional agent slug"
                onChange={(event) =>
                  changeContext({ agent_slug: event.target.value || null })
                }
              />
            </label>
            <label>
              Selection query
              <input
                value={context.query}
                onChange={(event) =>
                  changeContext({ query: event.target.value })
                }
              />
            </label>
            <button
              type="button"
              disabled={!context.session_id || busy}
              onClick={() =>
                void perform(async () => {
                  await contextRequest('/workflows', {
                    consumer_surface: context.consumer_surface,
                    session_id: context.session_id,
                    workflow_ids: context.workflow_ids,
                  })
                  setNotice(
                    'Workflow activation saved for this session. It takes effect when the client next requests context.',
                  )
                })
              }
            >
              Save workflow activation for session
            </button>
          </div>
        </details>
        <p>
          These selectors change the preview. Source scope changes are staged in
          the inspector.
        </p>
      </section>
      {(error || query.error) && (
        <div role="alert" className={styles.error}>
          {error ??
            (query.error instanceof Error
              ? query.error.message
              : 'Unable to load context')}
        </div>
      )}
      {notice && (
        <p role="status" className={styles.notice}>
          {notice}
        </p>
      )}
      {delivery?.status === 'failed' && (
        <p role="alert" className={styles.error}>
          Context generation failed: {delivery.failure?.error_message}
        </p>
      )}
      <div className={styles.toolbar}>
        <input
          aria-label="Search context"
          placeholder="Search names, content or scope…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <select
          aria-label="Filter context"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        >
          {[
            'all',
            'included',
            'excluded here',
            'not applicable',
            'prompt',
            'memory',
            'computed',
            'changed',
            'review available',
            'stale review',
          ].map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
        <span>
          {rows.length} sources ·{' '}
          {delivery?.estimated_tokens.toLocaleString() ?? '…'} generated tokens
          {preview &&
            ` (${(preview.token_delta ?? 0) >= 0 ? '+' : ''}${preview.token_delta ?? 0})`}
        </span>
        <button type="button" onClick={() => setShowRendered(!showRendered)}>
          Exact rendered context
        </button>
      </div>
      {showRendered && (
        <section className={styles.rendered}>
          <p>
            Generated preview only. Binding, observed model delivery, retrieval
            and saved session context are separate evidence stages.
          </p>
          {preview?.baseline && (
            <details>
              <summary>
                Before · {preview.baseline.estimated_tokens} tokens
              </summary>
              <pre>{preview.baseline.rendered}</pre>
            </details>
          )}
          <pre>{delivery?.rendered}</pre>
        </section>
      )}
      {checked.length > 0 && (
        <section className={styles.bulk} aria-label="Bulk context changes">
          <strong>{checked.length} selected</strong>
          <label>
            Scope
            <select
              value={bulkScope}
              onChange={(event) =>
                setBulkScope(event.target.value as ContextPolicy['scope'])
              }
            >
              <option value="project">Project</option>
              <option value="global">Global</option>
              <option value="agent">Agent</option>
            </select>
          </label>
          <label>
            Target
            <input
              list="context-projects"
              value={bulkTarget}
              onChange={(event) => setBulkTarget(event.target.value)}
            />
          </label>
          <button
            type="button"
            onClick={() =>
              bulkSources.forEach((source) => {
                if (source.policy)
                  stage(source, {
                    policy: {
                      ...(edits[sourceKey(source)]?.policy ?? source.policy),
                      scope: bulkScope,
                      targets: bulkScope === 'global' ? [] : list(bulkTarget),
                    },
                  })
              })
            }
          >
            Stage scope
          </button>
          <label>
            Loads
            <select
              value={bulkActivation}
              onChange={(event) =>
                setBulkActivation(
                  event.target.value as ContextPolicy['activation'],
                )
              }
            >
              <option value="always">Upfront</option>
              <option value="on_demand">On demand</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() =>
              bulkSources.forEach((source) => {
                if (source.policy)
                  stage(source, {
                    policy: {
                      ...(edits[sourceKey(source)]?.policy ?? source.policy),
                      activation: bulkActivation,
                    },
                  })
              })
            }
          >
            Stage disclosure
          </button>
          <button
            type="button"
            onClick={() =>
              bulkSources.forEach((source) => place(source, 'exclude'))
            }
          >
            Exclude here
          </button>
          <button
            type="button"
            onClick={() =>
              bulkSources.forEach((source) => place(source, 'inherit'))
            }
          >
            Restore inherited selection
          </button>
          <button
            type="button"
            onClick={() =>
              bulkSources.forEach((source) => stage(source, { enabled: true }))
            }
          >
            Stage enable
          </button>
          <button
            type="button"
            onClick={() =>
              bulkSources.forEach((source) => stage(source, { enabled: false }))
            }
          >
            Stage disable
          </button>
          <button
            type="button"
            onClick={() =>
              bulkSources
                .filter((source) => source.source_type === 'memory')
                .forEach((source) => stage(source, { archive: true }))
            }
          >
            Stage memory archive
          </button>
          <button type="button" onClick={() => setChecked([])}>
            Clear selection
          </button>
        </section>
      )}
      <datalist id="context-projects">
        {projects.data?.map((project) => (
          <option key={project.project_id} value={project.project_id} />
        ))}
      </datalist>
      <datalist id="context-agents">
        {agents.data?.agents.map((agent) => (
          <option key={agent.slug} value={agent.slug}>
            {agent.name}
          </option>
        ))}
      </datalist>
      <div className={styles.workspace}>
        <div className={styles.tableWrap} aria-busy={query.isFetching}>
          <table>
            <thead>
              <tr>
                <th>Select</th>
                <th>Name / kind</th>
                <th>Applies to</th>
                <th>Loads</th>
                <th>Format</th>
                <th>State and reason</th>
                <th>Tokens</th>
                <th>Review</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((source) => {
                const key = sourceKey(source)
                const edit = edits[key]
                const policy = edit?.policy ?? source.policy
                return (
                  <tr
                    key={key}
                    className={key === selected ? styles.selected : undefined}
                  >
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Select ${source.name}`}
                        checked={checked.includes(key)}
                        onChange={(event) =>
                          setChecked((current) =>
                            event.target.checked
                              ? [...current, key]
                              : current.filter((item) => item !== key),
                          )
                        }
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        className={styles.sourceName}
                        onClick={() => setSelected(key)}
                      >
                        {edit?.name ?? source.name}
                      </button>
                      <small>
                        {source.source_type} · {source.authority}
                        {edit || placements[key] ? ' · staged' : ''}
                      </small>
                    </td>
                    <td>
                      {policy
                        ? `${policy.scope}${policy.targets.length ? `: ${policy.targets.join(', ')}` : ''}`
                        : 'Computed'}
                      {policy?.workflows.length ? (
                        <small>
                          or workflow: {policy.workflows.join(', ')}
                        </small>
                      ) : null}
                    </td>
                    <td>
                      {policy?.activation === 'always'
                        ? 'Upfront'
                        : (policy?.activation.replace('_', ' ') ?? 'Runtime')}
                    </td>
                    <td>{policy?.format ?? 'Full'}</td>
                    <td>
                      {placements[key]?.mode
                        ? `${placements[key].mode} (staged)`
                        : source.state}
                      <small>{source.reason}</small>
                    </td>
                    <td>{source.tokens.toLocaleString()}</td>
                    <td>{source.review_status ?? 'Not reviewed'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {!query.isFetching && rows.length === 0 && (
            <p className={styles.empty}>No sources match these filters.</p>
          )}
        </div>
        {active ? (
          <ContextInspector
            source={active}
            edit={draftActive}
            context={context}
            history={history.data ?? []}
            findings={review?.findings ?? []}
            onStage={(change) => stage(active, change)}
            onRetrieve={() =>
              changeContext({
                requested_source_ids: context.requested_source_ids.includes(
                  active.source_id,
                )
                  ? context.requested_source_ids.filter(
                      (id) => id !== active.source_id,
                    )
                  : [...context.requested_source_ids, active.source_id],
              })
            }
            onPlace={(mode) => place(active, mode)}
            onProposal={(id) => {
              setProposalId(id)
              setNotice(
                'This draft is linked to review evidence. Saving will check that the evidence is still current.',
              )
            }}
            onUndo={(id) =>
              void perform(async () => {
                await contextRequest(`/changes/${id}/undo`, {})
                setEdits({})
                setPlacements({})
                setPreview(null)
                await query.refetch()
                await history.refetch()
                setNotice('Change undone as a new history entry.')
              })
            }
            onFeedback={(payload) =>
              void perform(async () => {
                await contextRequest('/feedback', payload)
                await history.refetch()
                setNotice(
                  'Explicit feedback recorded separately from citation and delivery signals.',
                )
              })
            }
          />
        ) : (
          <aside className={styles.inspector}>
            <h2>Inspect a source</h2>
            <p>
              Select a name to edit its scope, disclosure and content, see why
              it applies, or review history.
            </p>
            <p>
              Computed capabilities stay owned by their registry. Native system
              prompts are preserved and may be unobservable.
            </p>
          </aside>
        )}
      </div>
      <section className={styles.review}>
        <h2>Context review</h2>
        <details>
          <summary>Compare a visible native prompt</summary>
          <p>
            Only text you supply is compared. This does not expose or verify
            hidden provider instructions.
          </p>
          <label>
            Native prompt snapshot
            <textarea
              rows={6}
              value={nativeText}
              onChange={(event) => {
                setNativeText(event.target.value)
                setReview(null)
              }}
            />
          </label>
        </details>
        <p>
          Checks compare sources that can apply together in this preview.
          Findings are proposals; hidden native prompts cannot be audited.
          Lexical candidate selection can miss indirect conflicts.
        </p>
        <div className={styles.toolbar}>
          <label>
            Method
            <select
              value={reviewMode}
              onChange={(event) => {
                setReviewMode(event.target.value as typeof reviewMode)
                setReview(null)
              }}
            >
              <option value="deterministic">Deterministic checks</option>
              <option value="curator">Curator semantic review</option>
              <option value="jev">Experimental Jev screening</option>
            </select>
          </label>
          {reviewMode === 'jev' && (
            <label>
              Catalog model
              <select
                value={effectiveReviewModel}
                onChange={(event) => {
                  setReviewModel(event.target.value)
                  setReview(null)
                }}
              >
                <option value="">Select a typed model</option>
                {typedModels.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button
            type="button"
            disabled={busy || changes > 0}
            onClick={() => void reviewContext(true)}
          >
            Check and estimate
          </button>
          {reviewMode !== 'deterministic' && (
            <button
              type="button"
              disabled={busy || changes > 0 || !review}
              onClick={() => void reviewContext(false)}
            >
              Run requested review
            </button>
          )}
        </div>
        {changes > 0 && (
          <p>
            Save or discard staged edits before reviewing their durable
            revisions.
          </p>
        )}
        {review && (
          <>
            <p>
              {review.coverage.eligible_sources} eligible sources ·{' '}
              {review.coverage.candidate_pairs} candidate pairs · approximately{' '}
              {review.estimated_input_tokens.toLocaleString()} input tokens
              before reviewer instructions.
            </p>
            {review.reason && <p>{review.reason}</p>}
            {review.failure && <p className={styles.error}>{review.failure}</p>}
            {review.screening && (
              <>
                <p>
                  {review.screening.cache_hits} cached ·{' '}
                  {review.screening.new_calls} new calls · estimated new cost $
                  {review.screening.estimated_new_cost_usd.toFixed(6)}
                  {review.screening.actual_new_cost_usd !== undefined
                    ? ` · usage-priced new cost $${review.screening.actual_new_cost_usd.toFixed(6)}`
                    : ''}
                </p>
                <p>{review.screening.qualification}</p>
                <details>
                  <summary>Typed screening results</summary>
                  <pre>{JSON.stringify(review.screening.entries, null, 2)}</pre>
                </details>
              </>
            )}
            {review.findings.map((finding, index) => (
              <article
                key={`${finding.kind}-${index}`}
                className={styles.finding}
              >
                <strong>
                  {finding.kind}: {finding.explanation}
                </strong>
                <p>{finding.remedy}</p>
                <small>{finding.uncertainty}</small>
                {review.review_id && !!finding.proposed_edits?.length && (
                  <button
                    type="button"
                    onClick={() => {
                      setEdits((current) => ({
                        ...current,
                        ...Object.fromEntries(
                          (finding.proposed_edits ?? []).map((edit) => [
                            sourceKey(edit),
                            edit,
                          ]),
                        ),
                      }))
                      setProposalId(review.review_id)
                      setPreview(null)
                    }}
                  >
                    Stage proposed changes
                  </button>
                )}
                <details>
                  <summary>Exact passages</summary>
                  <pre>{JSON.stringify(finding.passages, null, 2)}</pre>
                </details>
              </article>
            ))}
            {review.findings.length === 0 && (
              <p>
                No deterministic findings. This does not establish that all
                context is necessary or conflict-free.
              </p>
            )}
            {review.review_id && (
              <button
                type="button"
                onClick={() => setProposalId(review.review_id)}
              >
                Link edits to this review
              </button>
            )}
          </>
        )}
      </section>
      {editWarnings.map((warning) => (
        <p className={styles.notice} key={warning}>
          {warning}
        </p>
      ))}
      {(preview ?? query.data)?.placement_warnings?.map((warning) => (
        <p className={styles.notice} key={sourceKey(warning)}>
          {warning.source_id}: {warning.reason}{' '}
          <button
            type="button"
            onClick={() => {
              setPlacements((current) => ({
                ...current,
                [sourceKey(warning)]: {
                  source_type: warning.source_type,
                  source_id: warning.source_id,
                  mode: 'inherit',
                },
              }))
              setPreview(null)
            }}
          >
            Stage removal of placement
          </button>
        </p>
      ))}
      {preview?.checks?.map((check, index) => (
        <p className={styles.notice} key={`${check.kind}-${index}`}>
          {check.explanation} {check.remedy}
        </p>
      ))}
      <footer className={styles.saveBar}>
        <strong>{changes} staged changes</strong>
        <label>
          Reason
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        <button
          type="button"
          disabled={busy || !changes}
          onClick={() => void previewChanges()}
        >
          Preview changes
        </button>
        <button
          type="button"
          className={styles.primary}
          disabled={
            busy || !changes || !preview || preview.delivery.status !== 'ok'
          }
          onClick={() => void saveChanges()}
        >
          Save reviewed changes
        </button>
        <button
          type="button"
          disabled={busy || !changes}
          onClick={() => {
            setEdits({})
            setPlacements({})
            setPreview(null)
            setProposalId(undefined)
          }}
        >
          Discard draft
        </button>
        {busy && <span role="status">Working…</span>}
      </footer>
    </main>
  )
}
