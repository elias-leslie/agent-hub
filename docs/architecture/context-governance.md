# Canonical context governance

Reusable instructions remain Agent Hub DB prompts. Memory remains citable knowledge with stable UUIDs; longer explanatory knowledge belongs in the Vault. This change does not introduce another policy store in a client or project file.

The Security Research policy was stored as a global prompt, while its project restriction existed only in prose. The old UI edited boot eligibility separately from the selector that loaded enabled globals. Migration `c7e92a160a31` gives it project scope `security-research` and explicit workflow activation of the same name; it is no longer global. Other existing globals and project placements are migrated without rewriting their contents. Migration `d8a30ef164b2` normalizes legacy project/agent scope encodings and indexes retained source evidence. Seed export preserves this metadata, and seeding remains insert-only.

## One selector and one renderer

`context_policy.py` interprets prompt policy and existing memory scope, applicability, triggers, tier and format. Memory disclosure metadata adds only activation and workflow names. Scope can be global, project, agent, or unassigned for a prompt. A matching explicit workflow can supplement scope; it cannot bypass consumer exclusions. Required applicable rules stay full and upfront or explicitly triggered. Advisory material can be relevant, conditional, or indexed for on-demand retrieval. Explicit retrieval returns the full body and preserves scope checks.

`runtime_context.py` owns final delivery for native clients, MCP, internal agents and the UI. Source eligibility precedes placement. Includes cannot make an unrelated or disabled source eligible. Agent ownership is separate and remains in the agent prompt stack. Computed tool guidance remains owned by its registry. No model is asked to decide authorization or required-rule inclusion.

Draft preview runs the exact assembler inside a rolled-back database savepoint. Save locks the placement layer and then source rows in stable order, checks source/placement revisions, applies the batch atomically, and records before/after snapshots. Undo is a new revision and rejects intervening edits. Memory edits preserve UUID, attribution and usage counts. Context records are separate from prompt/memory content and retain immutable review, change and feedback evidence.

## Operator workflow

Open Runtime Context, select the project, consumer and profile to inspect, then select a source name. Those selectors affect the preview. The inspector changes durable source scope, disclosure, format and targeting; include/exclude controls affect only the displayed project/profile. Owned and computed sources are visible but edited through their owners.

Stage one or several edits, inspect the exact before/after delivery and token delta, and save. Stale writes retain the draft for review. History includes batch undo and evidence. Dangling or ineffective placements are identified and can be staged for removal. Reference-selection policy remains available separately. Archive, disable, exclude here and on-demand disclosure are distinct operations.

Use the Why view to inspect a block or preview an advisory source's full retrieval. Explicit workflow activation can be saved for a known session/surface. It applies on the next supported context generation. It cannot retract messages already saved in a native thread; resume/fork remains the client's saved-context behavior.

## Reviews and honest evidence

Deterministic checks run without model calls. Semantic curator and Jev reviews are explicitly requested, preceded by a candidate/cost preview, and produce proposals only. Explicitly selected pairs are compared even without shared words. Unselected library discovery uses lexical overlap and can miss indirect contradictions; it is not advertised as exhaustive. Applicable agent-owned prompts and supplied visible native snapshots can be compared. Hidden native/provider instructions remain unobservable.

Review evidence retains exact passages and source revisions. Proposed edits enter the same staged workflow; their evidence is checked again under locks before save. Scheduled memory-curator work also stores proposals and never silently resizes, re-scopes, rewrites or archives memory. Unchanged reviewed versions are not repeatedly scheduled merely because no source mutation occurred.

Jev is a typed-judgment catalog entry, not a conversational/tool-running model. Its durable cache keys semantic content, effective short forms, scope, relevant consumer/task context, rubric and exact model version. Display names, counters, ordering of sets and source revision labels do not cause paid reclassification. Atomic reservation deduplicates concurrent dispatches; uncertain dispatches are retained and not automatically retried. Estimates and observed usage-priced costs are distinct from vendor billing. See [evaluation evidence](../evaluations/context-review/README.md).

User ratings, agent assessments, citations, generated context, bindings, observed delivery, retrieval and saved native context are separate signals. Legacy citation extraction remains supported, but citation no longer increments helpfulness. Automatic memory ratings retain their assessor/evidence and do not masquerade as owner feedback. Old utility counts are explicitly labelled as legacy mixed signals.

## Verification boundaries

Unit and UI tests cover scope, explicit workflows, exclusions, on-demand index/full retrieval, stale edits, preview rollback, cache identity, proposals and preserved draft state. A PostgreSQL integration test uses a disposable transactional schema inside `agent_hub_test` to verify real atomic save, rollback, undo and memory identity. Managed rebuilds apply migrations and seed the typed catalog entry. Live browser checks exercise project selection, source inspection, staged scope preview and discard; generation is checked through canonical CLI delivery. The native evaluation measures actual read-only task execution, with its limitations retained rather than inferred away.
