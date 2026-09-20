# Maintenance reviewer model qualification receipt

Date: 2026-09-19

Production decision: use `codex/gpt-5.6-luna` at low reasoning through the existing
Codex/ChatGPT subscription. The owner confirmed this selection after reviewing
the Gemini comparison. The curator has no automatic fallback chain and does not
use the OpenAI API or OpenAI API keys. Gemini's shared two-account rotation is
unchanged for other appropriate workloads. Reconsider curator use only with new
qualification evidence; this work adds no scheduled model benchmark.

This is a bounded, synthetic qualification of `memory-curator` through the
canonical `_call_reviewer_agent` path. It used the production regular memory
review schema and the production `RecoveryDecision` schema from
`context_maintenance_recovery.py`. The prompt fixtures contained only synthetic
incident, scope, duplicate, and required-policy text. No memory source rows
were changed.

## Gemini 3.8 Flash

- Requested model: `gemini-3.8-flash`; agent slug: `memory-curator`.
- Worker credentials were initialized through `init_worker_credentials()`.
- The initialized Gemini pool contained two accounts. The non-persistent
  `_create_client` observer recorded natural account ordinals in call order:
  `1` (regular/low), `2` (regular/medium), `1` (recovery/low), `2`
  (recovery/medium). No key value, hash, prefix, or suffix was recorded.
- Fallbacks were disabled in a detached route copy; no alternate model was
  returned or accepted.

The regular low call completed as `gemini-3.8-flash` (session
`b1e86070-8aa8-4302-b9fe-7fbdc86b391c`; ledger session/event model was
`gemini-3.8-flash`; 6,036 input and 2,013 output tokens) and parsed against the production `REVIEW_SCHEMA` with all
six synthetic UUIDs present. It correctly treated unsupported current-state
claims as `unknown`/`needs_action`, kept a dated historical incident, retargeted
the scope mismatch, and merged one exact duplicate into the other.

Adverse result: for the required preservation rule, it returned `archive` with
`needs_action`, even though its reason included `PROMPT_MIGRATION_REQUIRED`
and cited the exact higher-authority policy. That does not preserve the active
rule under the curator policy; retain this as an adverse qualification result.

The recovery low call completed as `gemini-3.8-flash` (session
`e55acc26-2ac2-4505-9c9f-366b64d00325`; ledger event model was
`gemini-3.8-flash`; 5,289 input and 241 output tokens). After the production fence-stripping step, the
`RecoveryDecision` validated as `dismiss`; it keyed both supplied source IDs
and quoted each source with an exact contiguous passage. It preserved the
dated incident when present state was unknown.

Both medium calls naturally selected pool ordinal 2 and received provider
`503 UNAVAILABLE` (“model currently experiencing high demand”). They produced
no returned model or successful ledger result. This is retained as provider
availability evidence, not a quality judgment.

A controlled medium rerun was warranted because the earlier failures were
transient availability errors. Using the unchanged fixture and normal shared
pool, the regular case naturally selected ordinal 1 and the recovery case
selected ordinal 2. Both again returned `503 UNAVAILABLE` before session
creation, with no token usage to report. This repeated result across both
accounts and both schemas provides availability evidence against using Gemini
medium for the maintenance route at this time; it does not establish a
reasoning-quality failure.

## Luna comparison

The first comparison attempt used the OpenAI API route and correctly produced
no result because the approved credential cache had zero `openai` keys. That
route is retained as a failed configuration path; it is not a Luna quality
result.

The canonical Codex OAuth route was then loaded from the DB model catalog
without seeding or editing catalog rows. `codex/gpt-5.6-luna` resolved to
`openai-codex-responses` with reasoning enabled. The same frozen prompts and
schemas completed at low reasoning:

- Regular review returned `codex/gpt-5.6-luna` in session
  `3aa3cfb3-563c-42d4-a0b5-75313ac6ccd2`; the session and event ledger also
  recorded that model (5,507 input and 1,784 output tokens). It parsed all six UUIDs. It kept the required rule
  active with `needs_action` and `PROMPT_MIGRATION_REQUIRED` because delivery
  to the reviewed consumer was not established. It archived the separate
  scope-conflict item with `needs_action`.
- Recovery returned `codex/gpt-5.6-luna` in session
  `0f7932ff-39a2-4192-98e4-a1518420183d`; it validated as `dismiss` with both
  exact source IDs and contiguous quotes (5,061 input and 191 output tokens).

The synthetic input packet and boundary rubric are in
`gemini-3.8-flash-maintenance-qualification-fixture.json`. The compact ledger
evidence is in `gemini-3.8-flash-maintenance-qualification-raw.json`, and the
complete successful response bodies are preserved in
`gemini-3.8-flash-maintenance-qualification-responses-full.md`. The narrow
packet reconstruction is `reconstruct_qualification_packet.py`; it performs no
provider calls. The original evaluation ran from an ephemeral inline script,
so the reconstruction is not claimed byte-for-byte identical. The boundary
requirements came from the owner/task instructions before calls, but the
standalone `answer_key` field was materialized after the calls and is not an
independently preregistered score.

## Decision evidence

Gemini 3.8 Flash demonstrated production-schema parsing and strong handling of
the missing-evidence, historical, scope, duplicate, and recovery quote cases,
but its required-policy archive proposal conflicts with the quarantine rule
when prompt delivery is unverified. Codex Luna preserved that rule and passed
the same recovery boundary. Gemini's adverse proposal remains retained for
review; this receipt does not by itself declare the model disqualified because
the recovery path correctly dismisses the unsupported stale finding and no
follow-up apply decision was tested. The ordinal-2 Gemini 503s remain provider
availability evidence. The controlled medium rerun also failed before session
creation on both pool ordinals, so Gemini should not be selected as the current
first-choice medium-reasoning maintenance model. On the bounded low-reasoning
evidence, Luna is the safer first choice for policy preservation, with Gemini
retained as a possible free-tier fallback after availability and the archive
proposal are addressed.
