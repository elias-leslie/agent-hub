# Local lab credential references — review proposal

Task: SummitFlow `task-edbb449b012a4fc8`. This is an isolated prototype for parent/owner
review. Do not enroll values, activate a command, merge, deploy or change permissions from
this document. The task remains claimed and open pending approval.

The parent relayed the approved direction on 2026-10-22: separate system/provider/host
secrets from target-scoped lab, synthetic and temporary credentials. Future hunter/recon
sandboxes or Proxmox VMs should receive only the credentials needed for their assignment.
Today's shared kasadis/root account cannot enforce that isolation.

## Recommendation

Extend Agent Hub's existing encrypted credential store with a reserved lab namespace and
stable references: `secret://lab/<target>/<actor>`. Keep existing system env files, provider
credentials, SSH identities and Nightshift elevated tokens in their existing locations and
workflows. Do not import those sources into the lab namespace or provide fallback to them.

This adds no vault, key source, credential agent, third-party harness patch or desktop
dependency. A reference is metadata, not a bearer credential or permission grant.
Enrollment requires the owner's classification of an existing credential as synthetic or
temporary; a caller labeling something synthetic is not proof of that classification.

## Sources examined and options

| Existing source | Findings | Fit |
| --- | --- | --- |
| ST SDK/home env | `st_sdk/credentials.py` loads Agent Hub identity/service auth; file exists, kasadis-owned 0600. No value reads in the inventory. | Keep for system authentication. Adding all lab secrets here mixes the owner-approved classes and exposes the whole file to consumers. |
| Agent Hub encrypted DB | Existing Fernet encryption and custody, generic Credential rows and provider cache. Metadata: 11 rows/8 provider names, none named Matomo/Neri. Public GET decrypts and partly masks values; not called during inventory. | Recommended source, with lab rows excluded from provider caching and the generic credential API. |
| GNOME Secret Service | Active desktop service; login collection currently unlocked, 24 items; session collection empty. No whole-word Matomo/Neri label or attribute match. No value method/unlock used. This shell lacks the usual session-bus environment; metadata works with an explicit bus address. | Supported existing desktop source, but adopting it here adds bus/unlock/session dependencies and still needs a scoped handoff for a VM. No matching actor entry was discovered. |
| Nightshift grants | Three existing root-only 0600 token files; metadata only. Existing code handles the fixed elevated GitHub/Proxmox/OmniNull kinds and injects into one child after a grant. | Keep specialized elevated credentials here. Generalizing its live approval/grant system is larger than the demonstrated lab lookup gap. |
| SSH/ST Proxmox | Host SSH identity/config metadata exists. ST code resolves env-backed Proxmox API config or uses its backend route; lab path disables elevated admin forwarding. No host/target SSH/API connection attempted. | Keep the owner-managed host access path. Do not hand these identities or API tokens to a target-scoped worker. |
| Neri/Aico | Neri validates/emits secret:// connection references but does not resolve them. Aico attaches with Tether's returned environment, without forwarding Aico's environment. | Neri stores references; launchers arrange delivery. Neither needs a separate credential store. |

The Agent Hub Vault is knowledge/context storage, not an established lab-secret interface.
No pass/op/bw/secret-tool/keepassxc-cli executable was present on the inspected PATH.
No additional store is proposed.

## Prototype and storage contract

The existing `credentials` table holds a lab bundle as:

- `provider = _lab_<target>`; target is the canonical Neri target identifier.
- `credential_type = <actor>`; actor is a stable lowercase alias, max 50 characters.
- `value_encrypted` uses the existing Fernet helper and configured Agent Hub key.
  The encrypted payload binds schema version, full reference, synthetic/temporary kind,
  optional UTC expiry and named string fields such as username/password.

There is no schema migration. Lab rows are hidden from general credential list/get/update/
delete/set-primary, and cannot enter the provider cache. Existing provider/system behavior
is retained. `prepare_lab_credential` prepares a row without persisting it. It is not
connected to enrollment, a route or a command. `resolve_lab_credentials` accepts a trusted
target scope and explicit reference/field selections; validates all scopes before querying;
queries only requested actors under that target; refuses missing/duplicate/foreign rows;
then decrypts and checks identity, expiry and fields. It returns no partial result on error.
Errors and object repr omit values. No fallback reads env files, SSH keys or provider keys.

The implementation is in:

- `backend/app/storage/lab_credentials.py`: source/reference and selection interface.
- `backend/app/services/system_credentials.py`: reserved lab provider namespace.
- `backend/app/services/credential_manager.py`: no lab decryption/cache admission.
- `backend/app/api/credentials.py`: exclude lab rows from the general credential interface.
- `backend/tests/lab_credentials/{conftest.py,test_lab_credentials.py}`: synthetic checks.

## Proposed global workflow after approval

There is no supported global lab lookup command today. The following is the concrete
interface to add after design approval, not an instruction to execute now:

1. Owner enrollment uses Agent Hub's existing encrypted storage and a protected input
   stream/file, never a secret argument or prompt. Preserve source credentials; do not
   automatically discover, import, rotate or create them. Serialize enrollment because
   the existing table has no unique constraint on a lab target/actor pair; duplicates
   must fail closed. Metadata listing returns target/actor references only, without
   decrypting or partly masking values.
2. Agent Hub owns an ST extension with metadata discovery and a child-process handoff,
   for example `st credentials refs --target TARGET` and
   `st credentials run --target TARGET --request selections.json -- <child>`.
   These are proposed command names, not installed commands. All local harnesses use
   the same facade; no Codex/Claude-specific configuration or harness patches are needed.
3. `selections.json` contains references and field names only. The trusted runner resolves
   the selected bundle and delivers it in an inherited pipe/file descriptor to the child.
   The descriptor number may be in an env var; secret values are not arguments, env vars,
   ordinary stdout, model context or logs. Close the handoff after consumption. Browser/
   HTTP adapters consume the descriptor inside trusted automation instead of having the
   model read the password. Do not promise child output is secret-safe without adapter
   verification: a trusted child can still disclose what it receives.
4. Store stable refs in Neri's existing access metadata where connection-wide. If a
   workflow needs separate admin/viewer actors, keep both refs in its owning actor
   selection metadata; do not collapse roles onto one shared default login or invent a
   new global Neri actor registry. That product integration is outside this prototype.

Agent Hub's retained native runtime has temporary HOME/CODEX_HOME and minimal environment;
it does not automatically inherit an interactive root's ST/home configuration. Its launcher
must supply the same scoped handoff explicitly. A remote VM receives the selected bundle,
not the Agent Hub encryption key, shared internal secret, DB access, home env, keyring bus,
host SSH identity, or Proxmox admin token.

## Trust and future isolation

The caller-provided `target` parameter is a selection restriction, not authentication.
Today kasadis/root can bypass it or read other local sources. No per-agent security claim
is made. Agent Hub's current owner dependency can accept flagged loopback callers; source
defaults do not establish the live override. A future sandbox must not gain the host's
owner endpoints through that bypass.

For an isolated hunter/recon/VM, the host-side launcher derives target/ref/field selection
from the approved assignment, resolves outside the sandbox, and supplies only that result.
The worker cannot choose another target, query the source directly, mount owner config or
reach unrestricted host owner/provider endpoints. Reuse the chosen sandbox/VM launch
contract; do not introduce a new credential daemon or auth-token scheme in this task.
Changing actual mounts, network reach, identity or trust is a separate owner-controlled
integration step. A process receiving a credential can retain it; resolution-time expiry
does not revoke an already delivered credential.

## Matomo unblock path

The active 5.14.1 manifest has lab-shell/primary-web connections with no credential_ref.
Read-only projections show 3 stored manifest versions and 153 target events, all without
secret:// or credential_ref. No matching keyring metadata or Agent Hub provider was found.
Neri's opaque-reference validator supplies no resolver. This establishes an absent approved
reference path; it does not establish lost credentials or nonexistent accounts.

Bugout `range/README.md:70-100` tells operators to retain application admin/test-user creds
in an “approved private secret source” without naming one. The private compose env fields
are database credentials, not admin/viewer logins. The recorded clean baseline retains a
synthetic superuser and a neutral site; a later viewer's existence is unverified.

After approval, a separately authorized trusted enrollment step must locate the retained
synthetic actors from operator custody without displaying values, confirm owner-approved
classification and enroll stable admin/viewer refs. Do not substitute database or host root
access for an application actor. If either actor is missing or its credentials are
ambiguous, report that fact for a specific provisioning decision; do not create, reset or
rotate it under this proposal. Bind the refs to the exact lab/workflow metadata, then
verify a bounded normal login only under separate runtime authority. No target contact,
credential enrollment, validity check or login occurred in this audit/prototype.

## Verification and limits

Run from the review worktree, using ST-managed admission and the existing read-only
dependency environment. Its backend/.venv symlink points to the existing canonical venv;
no dependency installation or modification was performed.

```sh
st check pytest -- --confcutdir=tests/lab_credentials -o pythonpath=. tests/lab_credentials -q -n 0
st check ruff -- backend/app/storage/lab_credentials.py backend/app/services/system_credentials.py backend/app/services/credential_manager.py backend/app/api/credentials.py backend/tests/lab_credentials
st check types
git diff --check
```

The focused tests exclude the root conftest that loads the home env file, use a disposable
Fernet key, guard against env-file opens and mock the DB. They cover scope rejection before
lookup/decryption, exact actor/field selection, expired/invalid payloads, duplicate rows,
provider cache separation, general API exclusion and no persistence. These are synthetic
module checks, not deployed/runtime credential evidence. No full suite is claimed.

Results on 2026-10-22: 28 focused tests passed in 2.40 seconds; managed Ruff and type
checks passed; changed-source gitleaks passed; `git diff --check` passed. Managed receipts
are retained under the review worktree's ignored `.dev-tools` directory. The successful
pytest receipt is `pytest-18e0e3b60e5949b7-1328281-c0f898c9-details.txt`; the type receipt
is `types-18e0e38be8d6dde3-1316372-8f7afd8a-details.txt`.

Audit limitation: a mistakenly placed --help after `st check --quick` started the general
gate. It was interrupted at pytest start because the normal fixture can read home env.
Whether that fixture ran before interruption is unverified. No credential contents appeared
in output; no manual env/private-key read or target contact occurred. Subsequent test runs
explicitly excluded that fixture. The quick gate is not claimed as passing.

The local-only checkpoint uses ST's supported `--skip-checks` recovery mode to preserve
this reviewed prototype without rerunning the incompatible general fixture. The explicit
managed checks above are the validation evidence; this is not full acceptance or approval
to merge/deploy.

Remaining risks: logical namespace separation shares the existing database/encryption key;
trusted root and backend remain able to read all source classes. Existing generic credential
storage helpers are privileged internals, not a sandbox interface. Duplicate rows fail
closed but enrollment has no DB uniqueness constraint. A future launcher must establish
scope and control child output/reach; this prototype does neither. No new reader endpoint
should be exposed using a worker-supplied target or general owner/loopback authorization.

## Parent approval handoff

Recommended single approval action for the parent to relay: **approve the reserved lab
namespace/source design and landing this inert prototype in Agent Hub, without enrollment,
new endpoints, activation or deployment.** That accepts a concrete source contract and
verified patch; it does not authorize credential access or the future runner/trust changes.
Keep this task open until the parent records the owner's decision. Do not ask the owner
directly from this worker.
