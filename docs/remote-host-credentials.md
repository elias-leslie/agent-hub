# Remote host credentials

Agents on a remote host (first host: the Proxmox VM `agent-work`) launch their
harness tools signed in, without borrowing the workstation's logins. Logins split by
whether they rotate. Design: aico `docs/plans/remote-hosts.md`, section "Credentials".

- **Non-rotating** (served): Agent Hub stores the value encrypted and hands it to a
  granted host at launch. Examples: Claude Code's `claude setup-token` token, and
  Pi's API keys for opencode-go and minimax.
- **Rotating** (host-only): the tool signs in on the host and the login stays on the
  host's disk. Examples: the Codex CLI, Pi's OAuth entries, and agy, which counts as
  rotating until its refresh token is shown not to rotate. Agent Hub only reports
  their status. Never hand Agent Hub's own Codex pair (`codex_credentials.py`) to a
  host: refresh-token reuse detection would break Agent Hub's Codex provider.

## Tool map (data)

`remote_tool_credentials` has one row per credential a Tether tool uses. It is
seeded by migration `c4f7a1e9d2b6` and edited with `st agents hosts tool-add` and
`tool-remove`. Each row records:

- the tool slug, a credential name, and the command the shim stands in for;
- the tool's real config dir;
- either an `env_var` or an `auth_file` under the config dir;
- `rotates`.

Served values live in `credentials` under provider `_host_tool_<tool>`. Like lab
rows, they stay out of the provider cache and the general credentials API.

## Hosts

`remote_hosts` holds each host's name, a SHA-256 hash of its bearer token, its
granted tools and when it was last seen.

```text
st agents hosts add NAME --token-out FILE   # token written once to a new 0600 file, never printed
st agents hosts grant|deny NAME TOOL
st agents hosts revoke NAME                 # token stops working, grants dropped
st agents hosts list | tools
st agents hosts credential-set TOOL NAME --input FILE|- [--expires-at ISO]
```

Owner API, behind `require_owner`:

- `GET|POST /api/remote-hosts`
- `DELETE /api/remote-hosts/NAME`
- `PUT|DELETE /api/remote-hosts/NAME/tools/TOOL`
- `GET|POST /api/remote-tools`
- `DELETE /api/remote-tools/TOOL/NAME`
- `PUT|DELETE /api/remote-tools/TOOL/NAME/credential`

None of these routes return a value, and only `POST /api/remote-hosts` returns a
token. Adding a revoked host again issues a new token with no grants.

Host-token API (`Authorization: Bearer <token>`; dependency `require_host` in
`app/api/remote_hosts.py`):

- `GET /api/host-credentials/tools`: the map, this host's grants, and whether each
  served value is stored and when it expires. It never returns values.
- `GET /api/host-credentials/TOOL`: the current, unexpired values for a granted
  tool. Responses are sent `Cache-Control: no-store`.
- `PUT /api/host-credentials/TOOL/NAME`: stores a non-rotating value for a granted
  tool.

`/api/host-credentials/` is exempt from the access-control middleware, so these
requests are never request-logged. Errors are fixed text. The host reaches Agent
Hub on its own loopback through the link's `ssh -R 8003` forward.

## On the host

`integrations/remote-host/agent-hub-host` uses only the Python standard library.
What it does depends on the name it runs under:

- `~/.local/bin/agent-hub`: the owner-facing command (`install`, `credential push`,
  `login status`, `native`).
- `~/.local/bin/agent-hub-cred-exec TOOL [ARGS]`: launches TOOL with its credentials.
- `~/.local/lib/agent-hub/cred-bin/<command>`: a shim for each granted tool that has
  a served credential. Codex and agy have no shim.

`cred-bin` must come first on the agent PATH, ahead of `~/.claude/bin` and the other
context launchers. The VM bootstrap sets that PATH in the tether unit and the login
shell. `~/.local/bin/<tool>` would not work for the shims, because the real
binaries live there and the Claude launcher execs `~/.local/bin/claude`.

The shim:

1. Fetches the tool's values.
2. Sets each env var, or writes a 0600 file under
   `$XDG_RUNTIME_DIR/agent-hub-creds/<tool>/` and symlinks it into the tool's real
   config dir. The config dir itself is never replaced, because Tether reads
   session files there.
3. Execs the next `<command>` on PATH, which is the context launcher.

`--version`, `--help`, `-v` and `-h` skip the fetch. Requests to Agent Hub never go through a proxy from the environment, since they carry the host token.

The shim fails closed with one line on stderr in these cases:

- no token or an unreadable token;
- Agent Hub is unreachable;
- the token is revoked;
- the tool isn't granted, or no value is stored;
- there is no private runtime dir;
- a real login file already sits where the link would go.

When it fails, the tool never starts.

Context launchers stay fail-open. Credential delivery is a separate step before them.

Host setup, after `st agents hosts add` and `grant`:

```text
ssh HOST 'agent-hub install --token-stdin' < TOKEN_FILE   # then delete TOKEN_FILE
```

The first time, run the installer by path from the checkout. Run `agent-hub install`
again after grants change; it adds and removes shims to match.

Sign-in on the host:

```text
agent-hub native claude setup-token        # run the real tool, no served credential
agent-hub credential push claude-code      # paste at the hidden prompt, or pipe it
codex login --device-auth                  # rotating: stays on this host
agent-hub login status --json
```

`login status` reports each tool as `signed_in`, `needs_sign_in`, `expired` or
`unknown`, with the source of each state:

- Served credentials come from `agent-hub`. A served credential is `needs_sign_in`
  when it isn't granted or nothing is stored. It is `unknown` when Agent Hub is
  unreachable; the last map is cached in `~/.config/agent-hub/tool-map.json`.
- Rotating logins come from `host:<path>`, decided by whether the login file exists
  and is readable.

Defaults: Agent Hub is `http://127.0.0.1:8003` (override with `AGENT_HUB_URL`). The
token is `~/.config/agent-hub/host-token` (override with
`AGENT_HUB_HOST_TOKEN_FILE`).
