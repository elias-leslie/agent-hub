# Agent hosts

An agent host is a machine where Tether runs agent sessions for the workstation:
Claude Code, Codex, Pi, agy and shells, with the workstation's hooks, context and
`st`. The first host is the Proxmox VM `agent-work` (VM 200, ssh alias
`agent-work`). The design is aico `docs/plans/remote-hosts.md`. Credentials are
covered in `docs/remote-host-credentials.md`.

Nothing on a host is durable. Work lands in git on the workstation, and a host
can be rolled back or rebuilt at any time.

## What a host gets

`scripts/remote-host/bootstrap <ssh-alias>` sets up all of the following. It is
re-runnable: a second run changes nothing unless the workstation changed.

- **Infra checkouts at the same paths.** The repos in `mirror.list` go under
  `/srv/workspaces/projects` as shallow checkouts of the workstation's
  committed HEAD.
  - That path is a real directory, not a link, because Agent Hub matches the
    resolved cwd against its project roots. A template that links it elsewhere
    (VM 9001 links it to `/work/projects`) gets the two swapped once.
  - A new host gets a depth-1 clone. Later runs send a git bundle of only the
    new commits, never the history, and nothing is pushed.
  - Only tracked files travel: no `.env`, credstore or ignored files.
  - A host checkout with local changes or commits is kept, and the run says so.
- **Harness CLIs at the workstation's versions:** claude, codex, pi, agy.
  - Each is copied from the workstation's install.
  - The Agent Hub context launchers in `~/.claude/bin` and `~/.codex/bin` and
    the Pi extension are installed through
    `integrations/context-delivery/install.py`.
  - The workstation's links from `~` into the mirrored repos (settings, hooks,
    skills, commands, bins) are recreated, plus the plain hook scripts the
    settings call.
  - No login is copied. Logins are served or signed in on the host, as
    described under Credentials.
- **Context delivery.** With no backend environment on the host,
  `agent-hub-context` falls through to `agent-hub-context-remote`. It posts to
  Agent Hub's `/api/host-context/deliver` over the `-R 8003` forward, using the
  host token in `~/.config/agent-hub/host-token`. Delivery fails open, like on
  the workstation. `sync-pi`, `bind-native-work-role` and the other subcommands
  that write local session records report that they are unavailable. So host
  transcripts are not ingested yet.
- **`st`.** `~/bin/st` is a guard (`host/st`) in front of the mirrored
  SummitFlow launcher, with the backend env from `uv sync --locked`.
  - Commands listed in `host/st-workstation-only` are refused at once with a
    reason and exit 2. They cover snapshots and rollback, services, the
    database, VMs, the desktop, the browser and secrets.
  - Everything else runs against the forwarded SummitFlow API (`-R 8001`). It
    authenticates with the agent token that Agent Hub serves through the `st`
    credential shim.
  - The SummitFlow database is never forwarded. Settings get a placeholder
    `DATABASE_URL` that nothing listens on. DB-backed parts of a command (such
    as some `st pulse` sections) report "connection refused" after
    SummitFlow's 30 s pool wait. API-backed parts answer normally.
- **PATH:** `cred-bin`, `~/.claude/bin`, `~/.codex/bin`, `~/bin`, `~/.local/bin`,
  then the system dirs.
  - `cred-bin` (`~/.local/lib/agent-hub/cred-bin`) holds Agent Hub's credential
    shims, installed by `agent-hub install`.
  - The same PATH is set in `~/.profile` (managed block) and in the
    `tether@default` drop-in `remote.conf`. Tether puts its own shims in front.
- **sshd:** `/etc/ssh/sshd_config.d/50-agent-host.conf` (`host/sshd-agent-host.conf`)
  allows 100 sessions per connection, since every remote terminal, paste and
  health check is one session on the Tether link's single connection (the
  OpenSSH default of 10 refuses the 11th). It also drops a dead link within
  about 45 s. Setup checks it with `sshd -t` and reloads sshd, which keeps open
  connections.
- **Tether:** the workstation's bundle in `~/.local/lib/tether` and
  `tether@.service` from the aico checkout.
  - The drop-in sets headless mode, the projects dir and the PATH.
  - `~/.config/tether/projects.json` comes from `st projects list`, so Tether
    knows the projects even while SummitFlow can't answer the host.
  - The daemon restarts only when the bundle, unit or drop-in changed.
    Restarting never stops a pane.
- **Idle poweroff:** `agent-host-idle.timer` runs every 5 min as root.
  - The host powers off once it has been idle for `IDLE_MINUTES`. Idle means
    no Tether sessions, no pending wakes, load below `LOAD_MAX`, no ssh
    connection that runs a shell or command (the Tether link is `ssh -N`), and
    no user work.
  - User work is any process left in a user slice, however little CPU it uses:
    a `setsid -f`/`nohup` job, a stray tmux, a `systemd-run --user` unit, or
    something left running after a Tether session ended. Tether's own units,
    the user manager and the usual user daemons (`IGNORE_UNITS`) and sshd's own
    processes (`IGNORE_COMMANDS`) don't count.
  - The thresholds are in `/etc/agent-host/idle.conf`. Re-runs never overwrite
    it; they only add keys it lacks. `ENABLED=0` turns poweroff off.
  - Anything that can't be read counts as busy.
  - Each run logs its decision: `journalctl -u agent-host-idle`.
  - To check without changing anything:
    `sudo /usr/local/lib/agent-host/agent-host-idle --dry-run`.

## Clean snapshots

```
scripts/remote-host/snapshot-clean agent-work 200 agent-host-ready
```

The host runs `prepare-clean-snapshot`, then `st vm snapshot` takes the snapshot.
- The host step refuses while anything runs: Tether sessions, tmux servers,
  root requests or wakes, running containers, another ssh session, or user
  work (as for idle poweroff).
- Otherwise it clears Tether's state, the per-session context artifacts and
  `/work/scratch`, then restarts Tether empty.
- Logins on the host are kept, so a snapshot taken after sign-in keeps them.
- To check readiness only: `ssh agent-work /usr/local/lib/agent-host/prepare-clean-snapshot --check`.

## Add a host

1. Make a VM, either way:
   - From VM 200's clean snapshot, which already has everything:
     `st vm clone 200 <newid> <name>`. The clone carries agent-work's Agent Hub
     token and tool map. Remove both before anything else
     (`rm ~/.config/agent-hub/host-token ~/.config/agent-hub/tool-map.json` on
     the clone) and enrol it fresh in step 4. The bootstrap refuses to run
     while a token for another host is there.
   - From the template: `st vm clone 9001 <newid> <name>`
     (`ubuntu-2404-agent-ready`), then run the bootstrap.
2. Add an ssh Host alias for it in `~/.ssh/config`. Use the alias everywhere,
   never the IP. Pin the key with `IdentityFile ~/.ssh/id_ed25519_davion_gem` and
   `IdentitiesOnly yes`, the key clones authorize. Without it, ssh falls back to
   the desktop keyring agent. Codex's sandbox doesn't have that agent, and the
   link fails if the desktop session ends.
3. Run `scripts/remote-host/bootstrap <alias>`.
4. Register it with Agent Hub under its ssh alias (the bootstrap checks that
   the host token belongs to that name). Write the token straight to a file and copy it
   to the host's `~/.config/agent-hub/host-token` (0600). Never print it.
   ```
   st agents hosts add <name> --token-out FILE
   st agents hosts grant <name> <tool>
   ```
   Then run `agent-hub install` on the host for the credential shims. Sign in
   the rotating tools (Codex, Pi OAuth, agy) on the host itself.
5. Add the host to `~/.config/tether/hosts.json` with its link
   (`tether-link@<name>`), then take a clean snapshot.

## Resize, roll back, remove

- **Resize:** `st vm resize <vmid> --cores N --memory MB [--restart]`. More
  disk: `st vm grow-disk`.
- **Roll back:** `st vm rollback <vmid> agent-host-ready`. It discards
  everything since the snapshot, including the VM's Proxmox config (a
  snapshot keeps it). Run the bootstrap afterwards to bring the checkouts and
  CLIs up to date. A snapshot from before 2026-10-30 03:00 resets VM 200's
  balloon minimum to 4096, which leaves agents waiting on the 6 GiB memory
  guard after a cold boot: run `ssh davion-gem qm set 200 --balloon 8192`.
- **Remove:**
  1. `st agents hosts revoke <name>`. The token stops working and its grants
     are dropped.
  2. Remove its hosts.json entry and ssh alias.
  3. Then `st vm destroy <vmid>`.
