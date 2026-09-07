# Private context integration checks

Public CI runs every backend test except the `private_context` group. Those 15 test cases exercise private companion repositories and remain required through the separate `private-context-integration` commit status.

The private `elias-leslie/codex-config` repository hosts `agent-hub-context.yml`. A maintainer must review the exact Agent Hub head commit, including dependency and test changes, before manually dispatching it. Do not automatically dispatch arbitrary PR code: even without credentials, code running alongside private files could disclose them.

From a trusted checkout of the private repository, run:

```sh
bash scripts/run-agent-hub-context-check.sh PR_NUMBER FULL_REVIEWED_HEAD_SHA
```

The helper verifies the PR head, marks its status pending, dispatches the private workflow, waits for its result, and reports only success or failure publicly. Logs remain in the private repository. A changed head needs a fresh review and run. Do not run this helper from unreviewed PR code.

The private workflow uses read-only credentials with persistence disabled, pinned actions, and selected companion files. The Claude repository uses a dedicated read-only deploy key stored only as a private-repository Actions secret. No private-repository token or key is added to Agent Hub, and no `pull_request_target` workflow is used.

For local verification with both companion repositories checked out beside Agent Hub:

```sh
cd backend
uv run pytest tests/integrations/test_context_delivery_adapters.py -m private_context --no-cov
```

Missing files or failed assertions must fail the private check. Do not replace them with conditional skips or publish private files to make public CI pass.
