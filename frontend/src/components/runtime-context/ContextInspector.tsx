'use client'

import { useState } from 'react'
import type {
  ContextFinding,
  ContextPolicy,
  ContextRecord,
  ContextSelection,
  ContextSource,
  PlacementEdit,
  SourceEdit,
} from '@/lib/api/context-management'
import styles from './context-manager.module.css'

interface Props {
  source: ContextSource
  edit?: SourceEdit
  context: ContextSelection
  history: ContextRecord[]
  findings: ContextFinding[]
  onStage: (change: Partial<SourceEdit>) => void
  onPlace: (mode: PlacementEdit['mode']) => void
  onUndo: (id: string) => void
  onProposal: (id: string) => void
  onFeedback: (payload: unknown) => void
  onRetrieve: () => void
}
const asList = (value: string) =>
  value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)

export function ContextInspector({
  source,
  edit,
  context,
  history,
  findings,
  onStage,
  onPlace,
  onUndo,
  onProposal,
  onFeedback,
  onRetrieve,
}: Props) {
  const [tab, setTab] = useState('rules')
  const [turnId, setTurnId] = useState('')
  const [assessment, setAssessment] = useState('useful')
  const [evidence, setEvidence] = useState('')
  const policy = edit?.policy ?? source.policy
  const readOnly =
    source.source_type === 'computed' || source.owner_agent_id !== null
  const updatePolicy = (change: Partial<ContextPolicy>) => {
    if (policy) onStage({ policy: { ...policy, ...change } })
  }
  const matchingFindings = findings.filter((finding) =>
    finding.source_ids.includes(source.source_id),
  )
  return (
    <aside className={styles.inspector} aria-label={`Inspect ${source.name}`}>
      <h2>{source.name}</h2>
      <p>
        {source.source_type} · {source.authority}
      </p>
      <nav aria-label="Inspector sections" className={styles.tabs}>
        {['rules', 'content', 'why', 'history', 'feedback'].map((value) => (
          <button
            type="button"
            key={value}
            aria-pressed={tab === value}
            onClick={() => setTab(value)}
          >
            {value}
          </button>
        ))}
      </nav>
      {readOnly && (
        <p>
          This source is managed by{' '}
          {source.source_type === 'computed'
            ? 'the canonical capability registry'
            : 'its owning agent'}
          . Its content is visible here for comparison.
        </p>
      )}
      {tab === 'rules' && policy && (
        <fieldset disabled={readOnly}>
          <label>
            Applies to
            <select
              value={policy.scope}
              onChange={(event) => {
                const scope = event.target.value as ContextPolicy['scope']
                const target =
                  scope === 'agent' ? context.agent_slug : context.project_id
                updatePolicy({
                  scope,
                  targets:
                    scope === 'global' || scope === 'unassigned' || !target
                      ? []
                      : [target],
                })
              }}
            >
              <option value="global">Every project</option>
              <option value="project">Specific project</option>
              <option value="agent">Specific agent</option>
              {source.source_type === 'prompt' && (
                <option value="unassigned">Unassigned</option>
              )}
            </select>
          </label>
          {['project', 'agent'].includes(policy.scope) && (
            <label>
              {policy.scope === 'project' ? 'Project' : 'Agent'} target
              <input
                list={
                  policy.scope === 'project'
                    ? 'context-projects'
                    : 'context-agents'
                }
                value={policy.targets.join(', ')}
                placeholder="Choose a target"
                onChange={(event) =>
                  updatePolicy({ targets: asList(event.target.value) })
                }
              />
            </label>
          )}
          <label>
            Also applies when workflow is explicitly active
            <input
              value={policy.workflows.join(', ')}
              placeholder="None"
              onChange={(event) =>
                updatePolicy({ workflows: asList(event.target.value) })
              }
            />
          </label>
          <label>
            Loads when
            <select
              value={policy.activation}
              onChange={(event) =>
                updatePolicy({
                  activation: event.target.value as ContextPolicy['activation'],
                })
              }
            >
              <option value="always">Upfront when applicable</option>
              <option value="triggered">Task or phase matches</option>
              <option value="on_demand">Explicitly requested</option>
              {source.source_type === 'memory' && (
                <option value="relevant">When relevant to the query</option>
              )}
            </select>
          </label>
          {policy.activation === 'triggered' && (
            <>
              <label>
                Task types
                <input
                  value={policy.task_types.join(', ')}
                  onChange={(event) =>
                    updatePolicy({ task_types: asList(event.target.value) })
                  }
                />
              </label>
              <label>
                Phases
                <input
                  value={policy.phases.join(', ')}
                  onChange={(event) =>
                    updatePolicy({ phases: asList(event.target.value) })
                  }
                />
              </label>
            </>
          )}
          <label>
            Authority
            <select
              value={policy.required ? 'required' : 'advisory'}
              onChange={(event) =>
                updatePolicy({
                  required: event.target.value === 'required',
                  format:
                    event.target.value === 'required' ? 'full' : policy.format,
                })
              }
            >
              <option value="required">Required rule</option>
              <option value="advisory">Advisory context</option>
            </select>
          </label>
          <label>
            Delivered format
            <select
              value={policy.format}
              disabled={policy.required}
              onChange={(event) =>
                updatePolicy({
                  format: event.target.value as ContextPolicy['format'],
                })
              }
            >
              <option value="full">Full text</option>
              <option value="compact">Approved compact text</option>
              <option value="summary">Approved summary</option>
            </select>
          </label>
          <details>
            <summary>Consumer targeting</summary>
            {[
              ['consumer_surfaces', 'Include consumers'],
              ['exclude_consumer_surfaces', 'Exclude consumers'],
              ['agent_slugs', 'Include agents'],
              ['exclude_agent_slugs', 'Exclude agents'],
              ['audience_tags', 'Include audience tags'],
            ].map(([key, label]) => (
              <label key={key}>
                {label}
                <input
                  value={(policy.applicability[key] ?? []).join(', ')}
                  placeholder="Any"
                  onChange={(event) =>
                    updatePolicy({
                      applicability: {
                        ...policy.applicability,
                        [key]: asList(event.target.value),
                      },
                    })
                  }
                />
              </label>
            ))}
            <p>Exclusions take precedence. Each filled dimension must match.</p>
          </details>
          <div className={styles.actions}>
            <button type="button" onClick={() => onPlace('exclude')}>
              Exclude in this preview project
            </button>
            <button type="button" onClick={() => onPlace('include')}>
              Request here
            </button>
            <button type="button" onClick={() => onPlace('inherit')}>
              Restore inherited selection
            </button>
          </div>
          <p>
            Placement never bypasses source scope. Default rule edits above
            affect all matching future deliveries.
          </p>
          <div className={styles.actions}>
            <button
              type="button"
              onClick={() =>
                onStage({ enabled: !(edit?.enabled ?? source.enabled) })
              }
            >
              {(edit?.enabled ?? source.enabled)
                ? 'Disable source everywhere'
                : 'Enable source'}
            </button>
            {source.source_type === 'memory' && (
              <button type="button" onClick={() => onStage({ archive: true })}>
                Archive memory
              </button>
            )}
          </div>
          {edit?.archive && (
            <p>
              Archive is staged. The source and its history will remain
              available.
            </p>
          )}
        </fieldset>
      )}
      {tab === 'content' && (
        <fieldset disabled={readOnly}>
          <label>
            Name
            <input
              value={edit?.name ?? source.name}
              onChange={(event) => onStage({ name: event.target.value })}
            />
          </label>
          <label>
            Canonical content
            <textarea
              rows={18}
              value={edit?.content ?? source.content}
              onChange={(event) => onStage({ content: event.target.value })}
            />
          </label>
          {!readOnly && (
            <label>
              Approved short form
              <textarea
                rows={5}
                value={edit?.summary ?? source.summary}
                onChange={(event) => onStage({ summary: event.target.value })}
              />
            </label>
          )}
          <p>
            Required rules always use full text. Memory edits preserve the UUID,
            targeting and usage history.
          </p>
        </fieldset>
      )}
      {tab === 'why' && (
        <>
          <p>
            <strong>{source.state}</strong> · {source.reason}
          </p>
          <p>
            {source.tokens} tokens · revision {source.revision}
          </p>
          {!readOnly && !policy?.required && (
            <button type="button" onClick={onRetrieve}>
              {context.requested_source_ids.includes(source.source_id)
                ? 'Clear explicit retrieval'
                : 'Preview full text here'}
            </button>
          )}
          <h3>Exact rendered block</h3>
          <pre>
            {source.rendered ?? 'This source is not in the generated context.'}
          </pre>
          {matchingFindings.map((finding, index) => (
            <article
              key={`${finding.kind}-${index}`}
              className={styles.finding}
            >
              <strong>{finding.kind}</strong>
              <p>{finding.explanation}</p>
              <p>{finding.remedy}</p>
              <small>{finding.uncertainty}</small>
            </article>
          ))}
          <p>
            Generated does not mean bound or observed in a model request. A
            citation does not establish usefulness. Hidden native instructions
            remain unobservable.
          </p>
        </>
      )}
      {tab === 'history' && (
        <>
          {history.length === 0 && (
            <p>
              No context-management history yet. Existing source revision
              history remains available in the prompt or memory editor.
            </p>
          )}
          {history.map((entry) => (
            <article key={entry.id} className={styles.finding}>
              <strong>{entry.kind.replaceAll('_', ' ')}</strong>
              <small>
                {new Date(entry.created_at).toLocaleString()} · {entry.actor}
              </small>
              <details>
                <summary>Evidence and changes</summary>
                <pre>{JSON.stringify(entry.payload, null, 2)}</pre>
              </details>
              {entry.kind === 'change' && (
                <button type="button" onClick={() => onUndo(entry.id)}>
                  Undo this entire change
                </button>
              )}
              {[
                'curator_proposal',
                'context_review',
                'context_screen',
              ].includes(entry.kind) && (
                <button type="button" onClick={() => onProposal(entry.id)}>
                  Link a draft to this proposal
                </button>
              )}
            </article>
          ))}
        </>
      )}
      {tab === 'feedback' && (
        <>
          <p>
            Optional structured feedback keeps conversation prose clean. This is
            a user assessment, separate from automatic delivery, retrieval and
            citation signals.
          </p>
          <label>
            Session
            <input
              value={context.session_id ?? ''}
              readOnly
              placeholder="Set session in preview controls"
            />
          </label>
          <label>
            Turn
            <input
              value={turnId}
              onChange={(event) => setTurnId(event.target.value)}
            />
          </label>
          <label>
            Assessment
            <select
              value={assessment}
              onChange={(event) => setAssessment(event.target.value)}
            >
              {[
                'useful',
                'unnecessary',
                'conflicting',
                'incorrect',
                'missing',
                'unknown',
              ].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          <label>
            What happened
            <textarea
              rows={4}
              value={evidence}
              onChange={(event) => setEvidence(event.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={
              !context.session_id ||
              !turnId ||
              !evidence ||
              source.source_type === 'computed'
            }
            onClick={() =>
              onFeedback({
                source_type: source.source_type,
                source_id: source.source_id,
                source_revision: source.revision,
                session_id: context.session_id,
                turn_id: turnId,
                assessment,
                actor_type: 'user',
                evidence,
              })
            }
          >
            Record feedback
          </button>
          <p>
            Old helpful counts are legacy mixed signals because earlier citation
            processing also credited helpfulness. Missing feedback means
            unknown.
          </p>
        </>
      )}
    </aside>
  )
}
