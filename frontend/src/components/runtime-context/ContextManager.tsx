'use client'

import { MarkdownContent } from '@agent-hub/chat-ui'
import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { useState } from 'react'
import { fetchAgents } from '@/lib/api/agents'
import {
  type ContextInventory,
  type ContextPolicy,
  type ContextRecord,
  type ContextSelection,
  type ContextSource,
  contextRequest,
  type PlacementEdit,
  type SourceEdit,
} from '@/lib/api/context-management'
import { fetchProjectCatalog } from '@/lib/api/project-permissions'
import { ContextEditor } from './ContextEditor'
import styles from './context-manager.module.css'
import { PolicyModal } from './PolicyModal'

type PlacementMode = PlacementEdit['mode']
type BulkAction = '' | 'scope' | 'enable' | 'disable' | 'archive'
interface RowDraft {
  original: ContextSource
  edit: SourceEdit
  context: ContextSelection
  placementMode: PlacementMode
  placement?: PlacementEdit
  placementRevision: string
}

const keyOf = (source: { source_type: string; source_id: string }) =>
  source.source_type + ':' + source.source_id
const canEdit = (source: ContextSource) =>
  source.source_type !== 'computed' && source.owner_agent_id === null
const displayName = (source: ContextSource) =>
  source.name.trim() ||
  source.content.split('\n')[0]?.trim().slice(0, 72) ||
  (source.source_type === 'memory' ? 'Untitled memory' : 'Untitled instruction')

function usedBy(
  source: ContextSource,
  projects: { project_id: string; label: string }[],
) {
  const policy = source.policy
  if (!policy) return 'Managed automatically'
  if (policy.scope === 'global') return 'All projects'
  if (policy.scope === 'unassigned')
    return policy.workflows.length
      ? 'Workflow: ' + policy.workflows.join(', ')
      : 'Not assigned'
  if (!policy.targets.length)
    return policy.workflows.length
      ? 'Workflow: ' + policy.workflows.join(', ')
      : policy.scope === 'agent'
        ? 'Choose an agent'
        : 'Choose a project'
  const targetNames = policy.targets
    .map(
      (target) =>
        projects.find((project) => project.project_id === target)?.label ||
        target,
    )
    .join(', ')
  return policy.workflows.length
    ? targetNames + ' or workflow: ' + policy.workflows.join(', ')
    : targetNames
}

function previewStatus(source: ContextSource) {
  switch (source.state) {
    case 'included':
      return 'Included in this preview'
    case 'indexed':
      return 'Available on request'
    case 'eligible, not selected':
      return 'Available, not included'
    case 'excluded here':
      return 'Left out of this preview'
    case 'disabled':
      return source.memory_status === 'archived' ? 'Archived' : 'Turned off'
    case 'agent owned':
      return 'Managed in agent settings'
    default:
      return 'Does not apply here'
  }
}

function previewReason(source: ContextSource) {
  if (source.state === 'included')
    return 'This item matches the preview settings.'
  if (source.state === 'indexed')
    return 'The agent can request the full text when needed.'
  if (source.state === 'eligible, not selected')
    return 'The agent can use this item, but it was not chosen for this preview.'
  if (source.state === 'excluded here')
    return 'This item is left out for the selected project.'
  if (source.state === 'disabled') return 'This item is turned off or archived.'
  if (source.state === 'agent owned')
    return 'Edit this item in its agent settings.'
  if (source.reason.includes('available on demand'))
    return 'The agent must request this item.'
  if (
    source.reason.includes('task trigger') ||
    source.reason.includes('phase trigger')
  )
    return 'The chosen task or phase does not match this item.'
  if (source.reason.includes('consumer'))
    return 'This item is set for a different app or agent.'
  return 'This item is set for a different project or agent.'
}

function changedSource(draft: RowDraft): SourceEdit | null {
  const { original, edit } = draft
  const result: SourceEdit = {
    source_type: edit.source_type,
    source_id: edit.source_id,
    expected_revision: edit.expected_revision,
  }
  if (edit.name !== undefined && edit.name !== original.name)
    result.name = edit.name
  if (edit.content !== undefined && edit.content !== original.content)
    result.content = edit.content
  if (edit.summary !== undefined && edit.summary !== original.summary)
    result.summary = edit.summary
  if (edit.enabled !== undefined && edit.enabled !== original.enabled)
    result.enabled = edit.enabled
  if (
    edit.policy !== undefined &&
    JSON.stringify(edit.policy) !== JSON.stringify(original.policy)
  )
    result.policy = edit.policy
  if (edit.archive && original.memory_status !== 'archived')
    result.archive = true
  return Object.keys(result).length > 3 ? result : null
}
const isDirty = (draft: RowDraft) =>
  Boolean(changedSource(draft) || draft.placement)

function validationError(draft: RowDraft): string | null {
  const edit = changedSource(draft)
  if (edit?.content !== undefined && !edit.content.trim())
    return 'Enter text before saving.'
  if (edit?.policy?.scope === 'project' && !edit.policy.targets.length)
    return 'Choose a project before saving.'
  if (edit?.policy?.scope === 'agent' && !edit.policy.targets.length)
    return 'Choose an agent before saving.'
  if (edit?.policy?.required && edit.policy.activation === 'on_demand')
    return 'Required instructions must be included when they apply.'
  if (draft.placement && !draft.context.project_id)
    return 'Choose a project before changing its exception.'
  return null
}

function changedItems(
  record: ContextRecord,
): { source_id: string; name: string }[] {
  const changes = record.payload.changes
  if (!Array.isArray(changes)) return []
  return changes.flatMap((change) => {
    if (!change || typeof change !== 'object') return []
    const before = (change as { before?: unknown }).before
    if (!before || typeof before !== 'object') return []
    const item = before as { source_id?: unknown; name?: unknown }
    if (typeof item.source_id !== 'string') return []
    return [
      {
        source_id: item.source_id,
        name: typeof item.name === 'string' && item.name ? item.name : 'Item',
      },
    ]
  })
}

function affectedIds(record: ContextRecord): string[] {
  const placementIds = record.payload.placement_source_ids
  return [
    ...changedItems(record).map((item) => item.source_id),
    ...(Array.isArray(placementIds)
      ? placementIds.filter((id): id is string => typeof id === 'string')
      : []),
  ]
}

function History({
  source,
  busy,
  onUndo,
}: {
  source: ContextSource
  busy: boolean
  onUndo: (entry: ContextRecord) => void
}) {
  const [open, setOpen] = useState(false)
  const history = useQuery({
    queryKey: ['agent-context-history', source.source_id],
    queryFn: () =>
      contextRequest<ContextRecord[]>(
        '/history?source_id=' + encodeURIComponent(source.source_id),
      ),
    enabled: open,
  })
  const changes = (history.data ?? []).filter(
    (entry) => entry.kind === 'change',
  )
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>History</summary>
      {history.isPending && open && <p>Loading changes…</p>}
      {history.error && <p role="alert">Could not load this item’s history.</p>}
      {!history.isPending && changes.length === 0 && <p>No changes yet.</p>}
      {changes.map((entry) => {
        const items = changedItems(entry)
        return (
          <div className={styles.historyEntry} key={entry.id}>
            <div>
              <strong>{new Date(entry.created_at).toLocaleString()}</strong>
              <p>
                {items.length > 1
                  ? 'Changed ' +
                    items.length +
                    ' items: ' +
                    items.map((item) => item.name).join(', ')
                  : 'Changed this item'}
              </p>
            </div>
            <button type="button" disabled={busy} onClick={() => onUndo(entry)}>
              Undo
            </button>
          </div>
        )
      })}
    </details>
  )
}

export function ContextManager() {
  const queryClient = useQueryClient()
  const [context, setContext] = useState<ContextSelection>({
    consumer_surface: 'codex',
    consumer_profile: 'agent_startup',
    project_id: null,
    capabilities: ['bash'],
    workflow_ids: [],
    requested_source_ids: [],
    query: 'startup context',
  })
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [drafts, setDrafts] = useState<Record<string, RowDraft>>({})
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [showIncluded, setShowIncluded] = useState(false)
  const [policyOpen, setPolicyOpen] = useState(false)
  const [bulkAction, setBulkAction] = useState<BulkAction>('')
  const [bulkScope, setBulkScope] = useState<ContextPolicy['scope']>('project')
  const [bulkTarget, setBulkTarget] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({})
  const [rowNotices, setRowNotices] = useState<Record<string, string>>({})

  const projects = useQuery({
    queryKey: ['context-projects'],
    queryFn: fetchProjectCatalog,
  })
  const agents = useQuery({
    queryKey: ['context-agents'],
    queryFn: () => fetchAgents(false),
  })
  const inventory = useQuery({
    queryKey: ['context-manager', context],
    queryFn: () => contextRequest<ContextInventory>('/inventory', context),
    placeholderData: keepPreviousData,
  })
  const previewUpdating = inventory.isPlaceholderData
  const sources = inventory.data?.sources ?? []
  const rows = sources.filter((source) => {
    const query = search.toLowerCase().trim()
    const matchesText =
      !query ||
      [
        source.name,
        source.content,
        source.summary,
        usedBy(source, projects.data ?? []),
      ].some((value) => value.toLowerCase().includes(query))
    return (
      matchesText &&
      (typeFilter === 'all' || typeFilter === source.source_type) &&
      (!showIncluded || source.state === 'included')
    )
  })
  const selectedSources = sources.filter(
    (source) => selected.has(keyOf(source)) && canEdit(source),
  )
  const selectedHasDrafts = selectedSources.some((source) =>
    Boolean(drafts[keyOf(source)]),
  )

  function clearSelection() {
    setSelected(new Set())
    setBulkAction('')
    setError(null)
  }

  function updateContext(change: Partial<ContextSelection>) {
    setContext((current) => ({ ...current, ...change }))
    clearSelection()
    setError(null)
    setNotice(null)
  }
  function toggleExpanded(key: string) {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }
  function startEdit(source: ContextSource) {
    const key = keyOf(source)
    if (!canEdit(source) || drafts[key] || inventory.isFetching) return
    const mode =
      inventory.data?.placements.find((item) => keyOf(item) === key)?.mode ??
      'inherit'
    setDrafts((current) => ({
      ...current,
      [key]: {
        original: structuredClone(source),
        edit: {
          source_type: source.source_type as 'prompt' | 'memory',
          source_id: source.source_id,
          expected_revision: source.revision,
        },
        context: structuredClone(context),
        placementMode: mode,
        placementRevision: inventory.data?.placement_revision ?? '',
      },
    }))
    setRowErrors((current) => ({ ...current, [key]: '' }))
    setRowNotices((current) => ({ ...current, [key]: '' }))
  }
  function updateEdit(key: string, change: Partial<SourceEdit>) {
    setDrafts((current) => {
      const draft = current[key]
      return draft
        ? {
            ...current,
            [key]: { ...draft, edit: { ...draft.edit, ...change } },
          }
        : current
    })
    setRowErrors((current) => ({ ...current, [key]: '' }))
  }
  function updatePlacement(key: string, mode: PlacementMode) {
    setDrafts((current) => {
      const draft = current[key]
      if (!draft) return current
      return {
        ...current,
        [key]: {
          ...draft,
          placement:
            mode === draft.placementMode
              ? undefined
              : {
                  source_type: draft.edit.source_type,
                  source_id: draft.edit.source_id,
                  mode,
                },
        },
      }
    })
    setRowErrors((current) => ({ ...current, [key]: '' }))
  }
  function cancelEdit(key: string) {
    setDrafts((current) => {
      const next = { ...current }
      delete next[key]
      return next
    })
    setRowErrors((current) => ({ ...current, [key]: '' }))
  }
  async function refreshSaved() {
    await inventory.refetch()
    await queryClient.invalidateQueries({ queryKey: ['agent-context-history'] })
  }
  async function saveRow(key: string) {
    const draft = drafts[key]
    if (!draft || busy) return
    const problem = validationError(draft)
    if (problem) {
      setRowErrors((current) => ({ ...current, [key]: problem }))
      return
    }
    const edit = changedSource(draft)
    if (!edit && !draft.placement) {
      cancelEdit(key)
      return
    }
    setBusy(true)
    setRowErrors((current) => ({ ...current, [key]: '' }))
    try {
      await contextRequest<ContextInventory>('/save', {
        context: draft.context,
        edits: edit ? [edit] : [],
        placements: draft.placement ? [draft.placement] : [],
        expected_placement_revision: draft.placementRevision,
        reason: 'Edited in Agent context',
      })
      cancelEdit(key)
      await refreshSaved()
      setRowNotices((current) => ({
        ...current,
        [key]:
          'Saved. Agents can use this change the next time they receive context.',
      }))
    } catch (failure) {
      setRowErrors((current) => ({
        ...current,
        [key]:
          failure instanceof Error
            ? failure.message
            : 'Could not save. Your changes are still here.',
      }))
    } finally {
      setBusy(false)
    }
  }
  async function undoChange(record: ContextRecord, rowKey: string) {
    if (busy) return
    const affected = affectedIds(record)
    if (
      affected.some((id) =>
        Object.values(drafts).some(
          (draft) => draft.edit.source_id === id && isDirty(draft),
        ),
      )
    ) {
      setRowErrors((current) => ({
        ...current,
        [rowKey]:
          'Save or cancel edits to these items before undoing this change.',
      }))
      return
    }
    setBusy(true)
    setRowErrors((current) => ({ ...current, [rowKey]: '' }))
    try {
      await contextRequest(
        '/changes/' + encodeURIComponent(record.id) + '/undo',
        {},
      )
      setDrafts((current) =>
        Object.fromEntries(
          Object.entries(current).filter(
            ([, draft]) => !affected.includes(draft.edit.source_id),
          ),
        ),
      )
      await refreshSaved()
      setRowNotices((current) => ({ ...current, [rowKey]: 'Change undone.' }))
    } catch (failure) {
      setRowErrors((current) => ({
        ...current,
        [rowKey]:
          failure instanceof Error
            ? failure.message
            : 'Could not undo this change.',
      }))
    } finally {
      setBusy(false)
    }
  }
  async function applyBulk() {
    if (busy || !bulkAction || !selectedSources.length) return
    if (selectedHasDrafts) {
      setError(
        'Save or cancel edits to the selected items before applying an action.',
      )
      return
    }
    if (bulkAction === 'scope' && bulkScope !== 'global' && !bulkTarget) {
      setError(bulkScope === 'agent' ? 'Choose an agent.' : 'Choose a project.')
      return
    }
    setError(null)
    const edits: SourceEdit[] = selectedSources.flatMap((source) => {
      if (
        bulkAction === 'archive' &&
        (source.source_type !== 'memory' || source.memory_status === 'archived')
      )
        return []
      if (bulkAction === 'enable' && source.enabled) return []
      if (bulkAction === 'disable' && !source.enabled) return []
      if (
        bulkAction === 'scope' &&
        source.policy?.scope === bulkScope &&
        source.policy.workflows.length === 0 &&
        (bulkScope === 'global'
          ? source.policy.targets.length === 0
          : source.policy.targets.length === 1 &&
            source.policy.targets[0] === bulkTarget)
      )
        return []
      const edit: SourceEdit = {
        source_type: source.source_type as 'prompt' | 'memory',
        source_id: source.source_id,
        expected_revision: source.revision,
      }
      if (bulkAction === 'scope' && source.policy)
        edit.policy = {
          ...source.policy,
          scope: bulkScope,
          targets: bulkScope === 'global' ? [] : [bulkTarget],
          workflows: [],
        }
      else if (bulkAction === 'enable') edit.enabled = true
      else if (bulkAction === 'disable') edit.enabled = false
      else if (bulkAction === 'archive') edit.archive = true
      return [edit]
    })
    if (!edits.length) {
      setNotice('These items already have that setting.')
      return
    }
    setBusy(true)
    try {
      await contextRequest<ContextInventory>('/save', {
        context,
        edits,
        placements: [],
        expected_placement_revision: inventory.data?.placement_revision ?? '',
        reason: 'Bulk change in Agent context',
      })
      setSelected(new Set())
      setBulkAction('')
      await refreshSaved()
      setNotice(
        'Updated ' + edits.length + (edits.length === 1 ? ' item.' : ' items.'),
      )
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : 'Could not apply this action.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1>Agent context</h1>
          <p>
            View and edit the instructions and memories your agents can use.
          </p>
        </div>
        <button
          type="button"
          disabled={inventory.isFetching}
          onClick={() => void inventory.refetch()}
        >
          Refresh
        </button>
      </header>
      <section className={styles.previewControls} aria-label="Preview settings">
        <div className={styles.previewFields}>
          <label>
            Project
            <select
              value={context.project_id ?? ''}
              onChange={(event) =>
                updateContext({ project_id: event.target.value || null })
              }
            >
              <option value="">No project</option>
              {projects.data?.map((project) => (
                <option key={project.project_id} value={project.project_id}>
                  {project.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            App
            <select
              value={context.consumer_surface}
              onChange={(event) => {
                const surface = event.target.value
                updateContext({
                  consumer_surface: surface,
                  capabilities: ['codex', 'claude_code', 'pi'].includes(surface)
                    ? ['bash']
                    : [],
                })
              }}
            >
              <option value="codex">Codex</option>
              <option value="claude_code">Claude Code</option>
              <option value="pi">Pi</option>
              <option value="agent_runtime">Agent Hub</option>
              <option value="mcp">MCP</option>
            </select>
          </label>
        </div>
        <details>
          <summary>Preview options</summary>
          <div className={styles.previewFields}>
            <label>
              Profile
              <select
                value={context.consumer_profile}
                onChange={(event) =>
                  updateContext({ consumer_profile: event.target.value })
                }
              >
                {(inventory.data?.profiles ?? [context.consumer_profile]).map(
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
                  updateContext({ task_type: event.target.value || null })
                }
              />
            </label>
            <label>
              Phase
              <input
                value={context.phase ?? ''}
                placeholder="Any"
                onChange={(event) =>
                  updateContext({ phase: event.target.value || null })
                }
              />
            </label>
          </div>
        </details>
        <details>
          <summary>View full preview</summary>
          <p>
            This is what Agent Hub would send with these settings. Existing
            conversations may still have older text.
          </p>
          {previewUpdating ? (
            <p role="status">Updating preview…</p>
          ) : inventory.data?.delivery.status === 'failed' ? (
            <p role="alert">Could not build the preview.</p>
          ) : (
            <pre>{inventory.data?.delivery.rendered ?? 'Loading preview…'}</pre>
          )}
        </details>
        <details>
          <summary>Optional memory settings</summary>
          <button type="button" onClick={() => setPolicyOpen(true)}>
            Set how many optional memories to include
          </button>
        </details>
      </section>
      <PolicyModal
        profile={context.consumer_profile}
        isOpen={policyOpen}
        onClose={() => {
          setPolicyOpen(false)
          void inventory.refetch()
        }}
      />
      <div className={styles.toolbar}>
        <input
          type="search"
          aria-label="Search instructions and memories"
          placeholder="Search instructions and memories"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            clearSelection()
          }}
        />
        <label>
          Type
          <select
            value={typeFilter}
            onChange={(event) => {
              setTypeFilter(event.target.value)
              clearSelection()
            }}
          >
            <option value="all">All</option>
            <option value="prompt">Instructions</option>
            <option value="memory">Memories</option>
            <option value="computed">Other</option>
          </select>
        </label>
        <label className={styles.inlineCheck}>
          <input
            type="checkbox"
            checked={showIncluded}
            onChange={(event) => {
              setShowIncluded(event.target.checked)
              clearSelection()
            }}
          />
          Included in preview
        </label>
        <span>
          {rows.length} {rows.length === 1 ? 'item' : 'items'}
        </span>
      </div>
      {(error || inventory.error) && (
        <p role="alert" className={styles.error}>
          {error ??
            (inventory.error instanceof Error
              ? inventory.error.message
              : 'Could not load items.')}
        </p>
      )}
      {notice && (
        <p role="status" className={styles.notice}>
          {notice}
        </p>
      )}
      {previewUpdating && <p role="status">Updating preview…</p>}
      {inventory.isPending && <p>Loading instructions and memories…</p>}
      {!inventory.isPending && !inventory.error && rows.length === 0 && (
        <p className={styles.empty}>No items match your search or filters.</p>
      )}
      {selectedSources.length > 0 && (
        <section className={styles.bulk} aria-label="Selected items">
          <strong>{selectedSources.length} selected</strong>
          <label>
            Actions
            <select
              value={bulkAction}
              onChange={(event) =>
                setBulkAction(event.target.value as BulkAction)
              }
            >
              <option value="">Choose an action</option>
              <option value="scope">Change where used</option>
              <option value="enable">Turn on</option>
              <option value="disable">Turn off</option>
              {selectedSources.every(
                (source) => source.source_type === 'memory',
              ) && <option value="archive">Archive memories</option>}
            </select>
          </label>
          {bulkAction === 'scope' && (
            <>
              {selectedSources.some(
                (source) => source.policy?.workflows.length,
              ) && (
                <p>
                  This also removes the selected items’ workflow exceptions.
                </p>
              )}
              <label>
                Used by
                <select
                  value={bulkScope}
                  onChange={(event) => {
                    setBulkScope(event.target.value as ContextPolicy['scope'])
                    setBulkTarget('')
                  }}
                >
                  <option value="global">All projects</option>
                  <option value="project">A project</option>
                  <option value="agent">An agent</option>
                </select>
              </label>
              {bulkScope === 'project' && (
                <label>
                  Project
                  <select
                    value={bulkTarget}
                    onChange={(event) => setBulkTarget(event.target.value)}
                  >
                    <option value="">Choose a project</option>
                    {projects.data?.map((project) => (
                      <option
                        key={project.project_id}
                        value={project.project_id}
                      >
                        {project.label}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {bulkScope === 'agent' && (
                <label>
                  Agent
                  <select
                    value={bulkTarget}
                    onChange={(event) => setBulkTarget(event.target.value)}
                  >
                    <option value="">Choose an agent</option>
                    {agents.data?.agents.map((agent) => (
                      <option key={agent.slug} value={agent.slug}>
                        {agent.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </>
          )}
          {selectedHasDrafts && (
            <p>
              Save or cancel edits to the selected items before applying an
              action.
            </p>
          )}
          <button
            type="button"
            disabled={
              busy || !bulkAction || selectedHasDrafts || inventory.isFetching
            }
            onClick={() => void applyBulk()}
          >
            Apply
          </button>
          <button type="button" onClick={clearSelection}>
            Clear selection
          </button>
        </section>
      )}
      <div className={styles.listHeader} aria-hidden="true">
        <span />
        <span>Name</span>
        <span>Type</span>
        <span>Used by</span>
        <span>In this preview</span>
      </div>
      <div
        role="list"
        className={
          previewUpdating
            ? styles.sourceList + ' ' + styles.updating
            : styles.sourceList
        }
        aria-busy={inventory.isFetching}
        aria-hidden={previewUpdating}
        inert={previewUpdating}
      >
        {rows.map((source) => {
          const key = keyOf(source)
          const open = expanded.has(key)
          const draft = drafts[key]
          const placementMode =
            draft?.placement?.mode ??
            inventory.data?.placements.find((item) => keyOf(item) === key)
              ?.mode ??
            'inherit'
          return (
            <section role="listitem" key={key} className={styles.row}>
              <div className={styles.rowHeader}>
                <input
                  type="checkbox"
                  aria-label={'Select ' + displayName(source)}
                  checked={selected.has(key)}
                  disabled={!canEdit(source) || busy || inventory.isFetching}
                  onChange={() =>
                    setSelected((current) => {
                      const next = new Set(current)
                      if (next.has(key)) next.delete(key)
                      else next.add(key)
                      return next
                    })
                  }
                />
                <button
                  type="button"
                  className={styles.rowButton}
                  aria-label={displayName(source)}
                  aria-describedby={'summary-' + key}
                  aria-expanded={open}
                  disabled={inventory.isFetching}
                  onClick={() => toggleExpanded(key)}
                >
                  <strong>{displayName(source)}</strong>
                  <span>
                    {source.source_type === 'prompt'
                      ? 'Instruction'
                      : source.source_type === 'memory'
                        ? 'Memory'
                        : 'Other'}
                  </span>
                  <span>{usedBy(source, projects.data ?? [])}</span>
                  <span>{previewStatus(source)}</span>
                </button>
                <span id={'summary-' + key} className={styles.srOnly}>
                  {source.source_type === 'prompt'
                    ? 'Instruction'
                    : source.source_type === 'memory'
                      ? 'Memory'
                      : 'Other'}
                  . Used by {usedBy(source, projects.data ?? [])}.
                  {previewStatus(source)}.
                </span>
              </div>
              {open && (
                <div className={styles.rowBody}>
                  {draft ? (
                    <ContextEditor
                      source={draft.original}
                      edit={draft.edit}
                      projects={projects.data ?? []}
                      agents={agents.data?.agents ?? []}
                      context={draft.context}
                      placementMode={placementMode}
                      onChange={(change) => updateEdit(key, change)}
                      onPlacement={(mode) => updatePlacement(key, mode)}
                      onSave={() => void saveRow(key)}
                      onCancel={() => cancelEdit(key)}
                      busy={busy || inventory.isFetching}
                      error={rowErrors[key] || null}
                    />
                  ) : (
                    <>
                      <div className={styles.content}>
                        <MarkdownContent content={source.content} />
                      </div>
                      <p className={styles.previewNote}>
                        {previewStatus(source)}. {previewReason(source)}
                      </p>
                      {canEdit(source) ? (
                        <button
                          type="button"
                          disabled={busy || inventory.isFetching}
                          onClick={() => startEdit(source)}
                        >
                          Edit
                        </button>
                      ) : (
                        <p>
                          {source.source_type === 'computed'
                            ? 'This item is managed automatically.'
                            : 'Edit this item in its agent settings.'}
                        </p>
                      )}
                    </>
                  )}
                  {rowErrors[key] && !draft && (
                    <p role="alert" className={styles.error}>
                      {rowErrors[key]}
                    </p>
                  )}
                  {rowNotices[key] && (
                    <p role="status" className={styles.notice}>
                      {rowNotices[key]}
                    </p>
                  )}
                  {source.source_type !== 'computed' && (
                    <History
                      source={source}
                      busy={busy || inventory.isFetching}
                      onUndo={(entry) => void undoChange(entry, key)}
                    />
                  )}
                </div>
              )}
            </section>
          )
        })}
      </div>
    </main>
  )
}
