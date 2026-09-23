'use client'

import { useState } from 'react'
import type {
  ContextPolicy,
  ContextSelection,
  ContextSource,
  SourceEdit,
} from '@/lib/api/context-management'
import type { ProjectCatalogItem } from '@/lib/api/project-permissions'
import styles from './context-editor.module.css'

interface Props {
  source: ContextSource
  edit: SourceEdit
  projects: ProjectCatalogItem[]
  agents: { slug: string; name: string }[]
  context: ContextSelection
  placementMode: 'include' | 'exclude' | 'inherit'
  onChange: (change: Partial<SourceEdit>) => void
  onPlacement: (mode: 'include' | 'exclude' | 'inherit') => void
  onSave: () => void
  onCancel: () => void
  busy: boolean
  error: string | null
}

const applicabilityFields = [
  ['consumer_surfaces', 'Include apps'],
  ['exclude_consumer_surfaces', 'Exclude apps'],
  ['agent_slugs', 'Include agents'],
  ['exclude_agent_slugs', 'Exclude agents'],
  ['audience_tags', 'Include audience tags'],
] as const

function splitList(value: string) {
  return [
    ...new Set(
      value
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ]
}

export function ContextEditor({
  source,
  edit,
  projects,
  agents,
  context,
  placementMode,
  onChange,
  onPlacement,
  onSave,
  onCancel,
  busy,
  error,
}: Props) {
  const [targetSearch, setTargetSearch] = useState('')
  const [listDrafts, setListDrafts] = useState<Record<string, string>>({})
  const policy = edit.policy ?? source.policy
  const readOnly =
    source.source_type === 'computed' || source.owner_agent_id !== null
  const enabled = edit.enabled ?? source.enabled
  const singleTarget = source.source_type === 'memory'
  const missingTarget =
    policy &&
    (policy.scope === 'project' || policy.scope === 'agent') &&
    policy.targets.length === 0

  function updatePolicy(change: Partial<ContextPolicy>) {
    if (!policy) return
    const changedWhere =
      (change.scope !== undefined && change.scope !== policy.scope) ||
      (change.targets !== undefined &&
        JSON.stringify(change.targets) !== JSON.stringify(policy.targets))
    onChange({
      policy: {
        ...policy,
        ...change,
        workflows: changedWhere ? [] : (change.workflows ?? policy.workflows),
      },
    })
  }

  function listField(
    key: string,
    label: string,
    values: string[],
    update: (values: string[]) => void,
  ) {
    return (
      <label key={key} className={styles.field}>
        {label}
        <input
          value={listDrafts[key] ?? values.join(', ')}
          onChange={(event) => {
            const raw = event.target.value
            setListDrafts((current) => ({ ...current, [key]: raw }))
            update(splitList(raw))
          }}
          onBlur={() =>
            setListDrafts((current) => {
              const next = { ...current }
              delete next[key]
              return next
            })
          }
          placeholder="Separate values with commas"
          disabled={busy}
        />
      </label>
    )
  }

  const targets =
    policy?.scope === 'project'
      ? projects.map((project) => ({
          id: project.project_id,
          label: project.label,
        }))
      : policy?.scope === 'agent'
        ? agents.map((agent) => ({ id: agent.slug, label: agent.name }))
        : []
  const availableTargets = [
    ...targets,
    ...(policy?.targets ?? [])
      .filter((id) => !targets.some((target) => target.id === id))
      .map((id) => ({ id, label: id })),
  ]
  const filteredTargets = availableTargets.filter((target) =>
    `${target.label} ${target.id}`
      .toLowerCase()
      .includes(targetSearch.toLowerCase()),
  )

  return (
    <section className={styles.editor} aria-label={`Edit ${source.name}`}>
      {readOnly ? (
        <div className={styles.readOnly}>
          <p>
            {source.source_type === 'computed'
              ? 'This source is managed by the capability registry.'
              : 'Edit this source in its owning agent.'}
          </p>
          <button type="button" onClick={onCancel}>
            Close
          </button>
        </div>
      ) : (
        <>
          <fieldset className={styles.fields} disabled={busy}>
            <div className={styles.mainFields}>
              <label className={styles.field}>
                Name (optional)
                <input
                  value={edit.name ?? source.name}
                  onChange={(event) => onChange({ name: event.target.value })}
                />
              </label>
              <label className={styles.field}>
                Content
                <textarea
                  rows={8}
                  value={edit.content ?? source.content}
                  onChange={(event) =>
                    onChange({ content: event.target.value })
                  }
                  required
                />
              </label>
            </div>

            {policy && (
              <div className={styles.scope}>
                <label className={styles.field}>
                  Used by
                  <select
                    value={policy.scope}
                    onChange={(event) => {
                      const scope = event.target.value as ContextPolicy['scope']
                      const suggested =
                        scope === 'project'
                          ? context.project_id
                          : scope === 'agent'
                            ? context.agent_slug
                            : null
                      updatePolicy({
                        scope,
                        targets:
                          scope === policy.scope
                            ? policy.targets
                            : suggested
                              ? [suggested]
                              : [],
                      })
                      setTargetSearch('')
                    }}
                  >
                    <option value="global">Every project</option>
                    <option value="project">Selected projects</option>
                    <option value="agent">Selected agents</option>
                    {source.source_type === 'prompt' && (
                      <option value="unassigned">Unassigned</option>
                    )}
                  </select>
                </label>
                {policy.workflows.length > 0 && (
                  <p className={styles.hint}>
                    This item is also used during named workflows. Changing
                    where it is used removes those exceptions.
                  </p>
                )}
                {(policy.scope === 'project' || policy.scope === 'agent') && (
                  <div className={styles.targetPicker}>
                    <label className={styles.field}>
                      Find{' '}
                      {policy.scope === 'project' ? 'a project' : 'an agent'}
                      <input
                        type="search"
                        value={targetSearch}
                        onChange={(event) =>
                          setTargetSearch(event.target.value)
                        }
                      />
                    </label>
                    <div
                      className={styles.targetList}
                      role="group"
                      aria-label={
                        policy.scope === 'project' ? 'Projects' : 'Agents'
                      }
                    >
                      {filteredTargets.map((target) => (
                        <label key={target.id} className={styles.target}>
                          <input
                            type={singleTarget ? 'radio' : 'checkbox'}
                            name={
                              singleTarget
                                ? `target-${source.source_id}`
                                : undefined
                            }
                            checked={policy.targets.includes(target.id)}
                            onChange={(event) =>
                              updatePolicy({
                                targets: singleTarget
                                  ? [target.id]
                                  : event.target.checked
                                    ? [...policy.targets, target.id]
                                    : policy.targets.filter(
                                        (id) => id !== target.id,
                                      ),
                              })
                            }
                          />
                          <span>{target.label}</span>
                          {target.label !== target.id && (
                            <small>{target.id}</small>
                          )}
                        </label>
                      ))}
                      {filteredTargets.length === 0 && (
                        <p>
                          No matching{' '}
                          {policy.scope === 'project' ? 'projects' : 'agents'}.
                        </p>
                      )}
                    </div>
                    {missingTarget && (
                      <p className={styles.hint}>
                        Choose a target before saving.
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}

            <details className={styles.section}>
              <summary>More settings</summary>
              <div className={styles.detailFields}>
                <label className={styles.field}>
                  Short version
                  <textarea
                    rows={3}
                    value={edit.summary ?? source.summary}
                    onChange={(event) =>
                      onChange({ summary: event.target.value })
                    }
                  />
                </label>
                {policy && (
                  <>
                    <details className={styles.section}>
                      <summary>When this item is used</summary>
                      <div className={styles.detailFields}>
                        {listField(
                          'workflows',
                          'Also applies during workflows',
                          policy.workflows,
                          (values) => updatePolicy({ workflows: values }),
                        )}
                        <label className={styles.field}>
                          When to include
                          <select
                            value={policy.activation}
                            onChange={(event) =>
                              updatePolicy({
                                activation: event.target
                                  .value as ContextPolicy['activation'],
                              })
                            }
                          >
                            <option value="always">When applicable</option>
                            <option value="triggered">
                              Task or phase matches
                            </option>
                            <option value="on_demand">When requested</option>
                            {source.source_type === 'memory' && (
                              <option value="relevant">When relevant</option>
                            )}
                          </select>
                        </label>
                        {policy.activation === 'triggered' && (
                          <>
                            {listField(
                              'task_types',
                              'Task types',
                              policy.task_types,
                              (values) => updatePolicy({ task_types: values }),
                            )}
                            {listField(
                              'phases',
                              'Phases',
                              policy.phases,
                              (values) => updatePolicy({ phases: values }),
                            )}
                          </>
                        )}
                        <label className={styles.field}>
                          Importance
                          <select
                            value={policy.required ? 'required' : 'advisory'}
                            onChange={(event) => {
                              const required = event.target.value === 'required'
                              updatePolicy({
                                required,
                                format: required ? 'full' : policy.format,
                              })
                            }}
                          >
                            <option value="required">
                              Required instruction
                            </option>
                            <option value="advisory">
                              Optional information
                            </option>
                          </select>
                        </label>
                        <label className={styles.field}>
                          Text to send
                          <select
                            value={policy.format}
                            disabled={policy.required}
                            onChange={(event) =>
                              updatePolicy({
                                format: event.target
                                  .value as ContextPolicy['format'],
                              })
                            }
                          >
                            <option value="full">Full text</option>
                            <option value="compact">Short text</option>
                            <option value="summary">Summary</option>
                          </select>
                        </label>
                        <details className={styles.nestedDetails}>
                          <summary>App and agent filters</summary>
                          <div className={styles.detailFields}>
                            {applicabilityFields.map(([key, label]) =>
                              listField(
                                key,
                                label,
                                policy.applicability[key] ?? [],
                                (values) =>
                                  updatePolicy({
                                    applicability: {
                                      ...policy.applicability,
                                      [key]: values,
                                    },
                                  }),
                              ),
                            )}
                            <p className={styles.hint}>
                              This item is left out when an exclusion matches.
                            </p>
                          </div>
                        </details>
                      </div>
                    </details>

                    <details className={styles.section}>
                      <summary>For this project</summary>
                      <div className={styles.detailFields}>
                        {context.project_id ? (
                          <>
                            <p className={styles.hint}>
                              For{' '}
                              {projects.find(
                                (project) =>
                                  project.project_id === context.project_id,
                              )?.label ?? context.project_id}
                              . The item must still be allowed for this project.
                            </p>
                            <div
                              className={styles.choices}
                              role="group"
                              aria-label="Project exception"
                            >
                              {(
                                [
                                  ['inherit', 'Use normal settings'],
                                  ['include', 'Include in this project'],
                                  ['exclude', 'Leave out of this project'],
                                ] as const
                              ).map(([mode, label]) => (
                                <label key={mode}>
                                  <input
                                    type="radio"
                                    name={`placement-${source.source_id}`}
                                    checked={placementMode === mode}
                                    onChange={() => onPlacement(mode)}
                                  />
                                  {label}
                                </label>
                              ))}
                            </div>
                          </>
                        ) : (
                          <p className={styles.hint}>
                            Choose a project above to change this setting.
                          </p>
                        )}
                      </div>
                    </details>
                  </>
                )}

                <details className={styles.section}>
                  <summary>Turn on or archive</summary>
                  <div className={styles.detailFields}>
                    <label className={styles.checkbox}>
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={(event) =>
                          onChange({ enabled: event.target.checked })
                        }
                        disabled={edit.archive === true}
                      />
                      On
                    </label>
                    {source.source_type === 'memory' &&
                      source.memory_status !== 'archived' && (
                        <label className={styles.checkbox}>
                          <input
                            type="checkbox"
                            checked={edit.archive ?? false}
                            onChange={(event) =>
                              onChange({ archive: event.target.checked })
                            }
                          />
                          Archive memory
                        </label>
                      )}
                    {source.memory_status === 'archived' && (
                      <p className={styles.hint}>
                        Archived. Turn it on to make it available again.
                      </p>
                    )}
                    {edit.archive && (
                      <p className={styles.hint}>
                        Archiving keeps the memory and its history available.
                      </p>
                    )}
                  </div>
                </details>
              </div>
            </details>
          </fieldset>
          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              onClick={onSave}
              disabled={
                busy ||
                Boolean(missingTarget) ||
                !(edit.content ?? source.content).trim()
              }
            >
              {busy ? 'Saving…' : 'Save'}
            </button>
            <button type="button" onClick={onCancel} disabled={busy}>
              Cancel
            </button>
          </div>
        </>
      )}
    </section>
  )
}
