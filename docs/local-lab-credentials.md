# Local lab credential handoff

Agent Hub owns lab references in its existing encrypted `credentials` table.
Neri owns the target grant; the native operator owns account setup and login.
These commands neither grant target authority nor authenticate the human owner.

```text
st agents credentials refs --target TARGET
st agents credentials enroll --target TARGET --actor ACTOR --kind synthetic|temporary|account --input FILE|- [--expires-at ISO]
st agents credentials run --target TARGET --request selections.json -- /absolute/trusted-child [NONSECRET_ARGS]
st agents credentials refresh --target TARGET --actor ACTOR --input FILE|- [--expires-at ISO]
```

## Covered synthetic setup

An effective Neri local lab grant covers creating missing synthetic users/roles,
generating and enrolling their credentials, and establishing or renewing local
browser sessions needed for covered testing. Agents complete that setup without
an owner wait. Use the target's ordinary local setup/login path. Keep real or
ambiguous credentials, external accounts, new authority/scope, spending and
publication owner-controlled. The synthetic label alone grants no authority.
Only the owner may classify existing real/ambiguous material or approve external
account access; never relabel it to make a refresh succeed.

Trusted local setup code generates synthetic values internally and passes them
directly to enrollment or refresh. Do not display values in prompts, shell
history, transcripts, logs, reports or source control. Existing live credentials
come directly from their approved protected source. Never use shell literals,
argv, environment variables or here-documents to transfer credential values.

`--input FILE` opens a regular file without following its final symlink and
requires current-user ownership and no group/other permission bits. `--input -`
accepts piped stdin or a private regular file redirected to stdin; terminal input
is refused. Input is a JSON object mapping field names to nonempty strings.
Sources remain unchanged; remove replaceable private transfer files after use.

Enrollment creates `secret://lab/TARGET/ACTOR`: provider `_lab_TARGET`, type
`ACTOR`. Target/actor use lowercase letters, digits, dots, underscores and hyphens,
starting with a letter or digit; maximum lengths are 80/50. Field names use
identifier syntax. Temporary bundles require a future timezone-aware expiry;
synthetic bundles may have one. Expiry applies to the whole bundle.

Enrollment is insert-only. Refresh replaces the complete field map and expiry at
the same reference, preserving the row identity. Supply every field still needed;
omitting `--expires-at` makes the new synthetic bundle non-expiring. Refresh
requires exactly one existing, valid synthetic payload; its old expiry may have
passed. Missing, duplicate, malformed, foreign or temporary entries fail without
replacement. Renew the target credential/session first: refresh updates storage,
never resets a target account or creates a browser session. Both writes hold the
existing PostgreSQL table writer lock through validation and commit.

## Owner accounts

Kind `account` is a real login the owner lends agents (for example a bug bounty
platform account). Only the owner enrolls or classifies one; `st browser login
add TARGET` prompts them at a terminal and pipes the bundle here. Agents use it
only through `st browser login TARGET`, whose trusted adapter fills the page; the
values never reach the agent. Refresh keeps the account kind.

## Use and browser sessions

`refs` selects identity columns only. It does not fetch ciphertext, decrypt,
validate expiry or prove login validity. Check only the selected fields through
the relevant application path. An API token can authenticate API requests while
a fresh browser remains logged out. Establish a browser session through ordinary
login and verify the expected synthetic actor/role in that browser. A session
cookie or browser storage state is a separate secret. After expiry, log in again
and refresh the synthetic bundle; an invalid session proves no test outcome.

The request file contains references and field names only:

```json
[{"reference":"secret://lab/example-local/viewer","fields":["username","password"]}]
```

`run` checks exact target/actor scope, duplicates, payload integrity, expiry and
selected fields before launch. After its DB session closes, one trusted local
child receives an anonymous socket descriptor numbered by
`AGENT_HUB_LAB_CREDENTIAL_FD`. Read through EOF and close it. Its JSON contract is:

```text
{"schema_version":1,"target":"TARGET","credentials":[{"reference":"secret://lab/TARGET/ACTOR","values":{SELECTED_FIELDS}}]}
```

Only the descriptor number and standard executable search path reach the child's
environment. No host environment, stdin, DB session or encryption key is passed.
Child stdout/stderr are suppressed; only `exit_code` is returned. Failures emit a
fixed diagnostic without exceptions or values. JSON rejects duplicate keys; the
version 1 input/handoff limit is 65,536 bytes. Descriptors close on failure too.

Use a trusted application login/test adapter as the recipient. It may control an
isolated browser internally; never deliver the bundle to a general browser
process, shell, model harness or untrusted worker. The adapter must not disclose
values through files, network, subprocesses or logs. Restricted session output
may pass back through a private file for refresh; retain only sanitized results.

System/provider/SSH/host secrets keep their existing stores. Lab rows stay out of
the general credential API and provider cache. The source backend or installed
backend supplies existing DB/key custody, independent of the caller's cwd. There
is no second vault, HTTP resolver, auto-discovery or sandbox/VM isolation here.
