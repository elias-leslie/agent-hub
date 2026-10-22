# Local lab credential handoff

Task `task-25a8061a03524bd0` implements the owner-approved local handoff in
Agent Hub. Integration, deployment and live enrollment belong to the parent.
No live credential was enrolled or inspected, no Matomo request was made, and
no account was created or rotated while implementing this change.

Use the existing Agent Hub-owned ST namespace:

```text
st agents credentials enroll --target TARGET --actor ACTOR --kind synthetic|temporary --input FILE|- [--expires-at ISO]
st agents credentials refs --target TARGET
st agents credentials run --target TARGET --request selections.json -- /absolute/trusted-child [NONSECRET_ARGS]
```

The existing `agents` extension dispatches these commands; no SummitFlow or Neri
change, new namespace registration, HTTP endpoint or harness patch is required.
The extension needs Agent Hub's Python backend and existing configured DB/key
custody. It binds its own source backend or installed backend environment, never
the caller's working directory. The package entry point also accepts
`agent-hub-st agents credentials ...`. Static help loads no credential backend.
The backend pins the included `agent_hub_st-0.2.5-py3-none-any.whl` through its
pyproject and generated lock; the wheel includes the credential subcommands.

## Owner enrollment

Only the owner/operator may classify an existing actor as synthetic or temporary
and run enrollment. The shared kasadis/root account does not authenticate the
human owner; this command adds no per-agent authorization or approval system.

The input is a JSON object mapping field names to nonempty string values. Supply
it from a protected source directly, without displaying it to an agent, shell
history, terminal transcript or log. `--input FILE` opens a regular file without
following its final symlink and requires current-user ownership and no group or
other permission bits. `--input -` accepts piped stdin or a private regular file
redirected to stdin; interactive terminal input is refused. Do not use a shell
literal, argv, environment variable, here-document or agent-authored fixture to
transfer a live credential. The command does not delete or alter the source.

Enrollment creates `secret://lab/TARGET/ACTOR` in the existing encrypted
`credentials` table: provider `_lab_TARGET`, type `ACTOR`. Target and actor use
lowercase letters, digits, dots, underscores and hyphens, starting with a letter
or digit; maximum lengths are 80 and 50. Field names use identifier syntax.
Temporary credentials require a future timezone-aware expiry; synthetic ones
may have one. Expiry belongs to the whole actor bundle.

Enrollment is insert-only. A PostgreSQL transaction takes a
`SHARE ROW EXCLUSIVE` lock on `credentials`, checks the exact identity and inserts
only if absent. This serializes competing enrollment and table writers without a
schema migration; it briefly blocks provider writes too. One existing row or
duplicates cause failure without replacement. There is no update, reset, rotation
or automatic discovery. Direct privileged SQL can still bypass this contract.

System `.env`, provider credentials, SSH identities, host secrets and Nightshift
grants stay in their existing stores and workflows. Nothing imports or falls
back to them. The existing encryption key and DB configuration are used only by
the trusted source process and are not delivered to the child. Lab rows remain
excluded from the general credential API and provider cache.

## Metadata and selected child handoff

`refs` selects only provider/actor columns and returns `references`. It does not
fetch ciphertext, decrypt, mask values, validate expiry or prove login validity.
Malformed, duplicate or foreign identities fail closed.

The request file contains references and selected field names only, for example:

```json
[{"reference":"secret://lab/example-local/viewer","fields":["username","password"]}]
```

`run` validates all selections against the explicitly supplied target before
querying. It refuses duplicate actors/fields, missing or duplicate rows, foreign
identities, invalid encrypted payloads, expired bundles and missing fields. No
child starts after a resolution failure. JSON documents reject duplicate keys.
The version 1 input and handoff document limit is 65,536 bytes.

After the DB session closes, the trusted child receives an inherited anonymous
local socket descriptor. Its number is in `AGENT_HUB_LAB_CREDENTIAL_FD`; the only
other supplied environment entry is the standard executable search path. No
host environment, stdin, DB session or encryption key is forwarded. Other file
descriptors close on exec. The child must read the descriptor through EOF and
close it, consuming this JSON contract internally:

```text
{"schema_version":1,"target":"TARGET","credentials":[{"reference":"secret://lab/TARGET/ACTOR","values":{SELECTED_FIELDS}}]}
```

The runner queues the bounded bundle without blocking before launch, closes the
write direction and passes only the read endpoint. Insufficient socket capacity
fails before launch. There is no listener, disk file or external resolver. The
parent closes both endpoints on success or launch failure. Child stdout/stderr
are suppressed; the runner emits only `exit_code` and preserves child exit or
signal status. Operation failures emit a fixed diagnostic without exceptions,
tracebacks or values. Trusted children must still avoid disclosure through their
own files, network, subprocesses or logs. Do not run a general shell, browser,
model harness or untrusted worker as the recipient.

The launcher must derive target, actor and field selections from the approved
assignment. A caller-supplied target is a restriction, not authentication. This
local command does not establish VM/sandbox isolation or revoke a credential
already delivered. It is not an interface to expose to a sandbox or browser.
Neri reference binding, application login, remote transport and host isolation
are separate integration work; there is no general browser exposure here.

## Focused verification

From the isolated worktree, reuse the canonical dependency environment through
an ignored `backend/.venv` symlink. No dependencies are installed or modified.
The root test fixture reads home env, so exclude it explicitly:

```sh
st check pytest -- --confcutdir=tests/lab_credentials -o 'pythonpath=. ../packages/st-cli' tests/lab_credentials tests/st_cli/test_entrypoint.py -q -n 0
st check ruff -- backend/app/storage/lab_credentials.py backend/app/cli/lab_credentials.py backend/tests/lab_credentials backend/tests/st_cli/test_entrypoint.py packages/st-cli/agent_hub_st/lab_credentials.py packages/st-cli/agent_hub_st/agents.py
st check types
st check gitleaks --changed-only
git diff --check
```

Tests use a disposable encryption key, mock DB sessions and guard env-file reads.
They exercise enrollment ordering/rollback, metadata-only SQL, scope and expiry,
private file/stdin input, sanitized errors, descriptor cleanup and actual local
child consumption with synthetic values. They do not prove live credential
validity, PostgreSQL lock contention or deployed ST installation. No full suite,
acceptance, integration or deployment is claimed. The local checkpoint uses
`st commit --skip-checks` after these explicit managed checks, to avoid the general
gate's home-env fixture. Parent review/integration/deployment remains separate.

Verified on 2026-10-22: 67 focused tests passed; managed Ruff, types and
changed-source gitleaks passed; `git diff --check` passed. The managed receipts
are retained in this worktree's ignored `.dev-tools` directory.

The packaging follow-up built only our extension wheel and regenerated the lock
offline inside managed ST cleanrooms, using the existing Python 3.13.12
interpreter. A separate cleanroom installed the exact wheel into a disposable
venv and verified its installed console entrypoint's credential group and all
three command help pages, package version/location and backend lock consistency.
No shared dependency environment was changed. The receipt is
`.dev-tools/package-verification/packaged-st-smoke.json`. The focused packaging
test compares the pinned wheel's hash, version and Python source with this
checkout, so an outdated wheel fails verification. This verifies local package
installation, not deployment or any live credential operation.
