# CodeRabbit oversized diff review plan

> Current repo state no longer reproduces the 300-file PR on this checkout. `HEAD` and `origin/main` point to same commit `bcdf377f5208607bc4bcb74370e948a9f046322a`, so live diff here is `0` files. Evidence below uses reachable branch history to identify what caused prior oversized review failure.

## Evidence

- Current merge-base check: `git merge-base HEAD origin/main` => `bcdf377f5208607bc4bcb74370e948a9f046322a`
- Current unique file diff vs base: `0` files
- `.gitignore` already excludes common generated/vendor/local artifacts, including `.venv/`, `node_modules/`, `.next/`, `.dev-tools/`, `graphify-out/*`, `packages/graphiti/`, and `backend/.tmp/`.
- No repo-local evidence of a committed `cleanroom-pydeps` tree in current reachable branch tips.

## Major file-count drivers found in history

### 1. `21f9bae3` — Phase 4C: delete legacy text adapters
- File count: `173` files
- Alone exceeds CodeRabbit limit.
- Mostly broad adapter and test deletions across:
  - `backend/app/adapters/*`
  - `backend/tests/adapters/*`
  - `backend/tests/api/complete/*`
  - health/router cleanup files
- This is not generated churn. Real production/test surface. Must be split by concern, not hidden.

### 2. `bf4c9d04` — Remove Claude workload harness from Agent Hub
- File count: `135` files
- Near limit by itself.
- Main drivers:
  - removal of Claude auth/oauth/runtime files
  - deletion of many benchmark and worker scripts/tests
  - changes in backend runtime, API, frontend model UI, lockfile
- Fits under 150 alone, but leaves almost no room for unrelated follow-ups.

### 3. `2cf9b53b` — Simplify agent routing and restore tool schema execution
- File count: `76` files
- Main drivers:
  - four migrations
  - routing model deletions/replacements
  - backend API/schema removals
  - frontend agent page/model UI updates
- Valid review unit alone.

### 4. `51ce3699` — Phase 4D wave 2: delete sync tool loop
- File count: `36` files
- Mostly deletion sweep in `backend/app/api/complete/*` and matching tests.
- Valid review unit alone.

### 5. `79e2797c` — Phase 4E: sweep legacy result types
- File count: `32` files
- Cross-cutting but still reviewable as standalone.

## Root cause pattern

Oversized CodeRabbit failure did **not** come from generated/vendor junk on current evidence. Main cause was stacking several legitimate refactor/deletion waves into one review branch. Worst offender was `21f9bae3` alone at `173` files, which already breaks CodeRabbit even before other commits land.

Recurring cause:
- large architecture cleanups done as single commits
- multiple cleanup waves merged onto one branch before review
- branch kept accumulating after already-near-limit change (`bf4c9d04` at 135 files)

## Concrete mitigation path

### If oversized PR still exists on remote branch
1. Rebuild review stack into smaller PRs/changelists.
2. Hard split by concern, not by random file buckets.

Recommended split:
- **PR A:** `21f9bae3` split further into sub-PRs under 150 files:
  - adapters runtime deletion
  - adapter tests deletion
  - health/router collateral cleanup
- **PR B:** `51ce3699` sync tool loop deletion (`36` files)
- **PR C:** `79e2797c` legacy result types sweep (`32` files)
- **PR D:** `2cf9b53b` routing simplification + migrations (`76` files)
- **PR E:** `bf4c9d04` Claude workload harness removal (`135` files) with no unrelated follow-ups added

### If only goal is make CodeRabbit run again fastest
Use smallest safe review branch first:
- branch from `origin/main`
- cherry-pick one standalone reviewable unit under 150 files, e.g. `51ce3699`, `79e2797c`, or `2cf9b53b`
- open PR
- rerun CodeRabbit

### Generated/vendor trim path
Current checkout shows no missing `.gitignore` coverage for obvious local artifacts. So `.gitignore` change alone will not solve prior 300-file failure. If remote PR still includes committed generated/vendor trees, they must be removed from branch history or backed out in commits before review. Unstaging alone will not help an already-pushed PR history.

## Exact next action to rerun CodeRabbit successfully

Create a fresh PR branch containing **only one review unit under 150 files**. Best immediate candidate from history: `2cf9b53b` (`76` files) or `51ce3699` (`36` files). After opening that reduced-scope PR, rerun CodeRabbit on the new PR.

If remote oversized PR specifically must preserve the same end state, split `21f9bae3` first; it is the only identified single commit that independently violates the 150-file ceiling.

## Policy note for recurrence

Before requesting CodeRabbit on large refactors:
- check per-commit file count with `git show --stat --summary <sha>`
- if any single concern is near `120` files, stop stacking more work onto same PR
- if any single commit exceeds `150` files, split before review request
