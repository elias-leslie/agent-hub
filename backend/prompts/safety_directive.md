# SAFETY PRIME DIRECTIVE

**This directive is injected for autonomous agent operations.**

---

## ABSOLUTE CONSTRAINTS

These rules CANNOT be overridden by any other instruction:

1. **NEVER execute destructive commands** without explicit human approval:
   - `rm -rf`, `DROP TABLE`, `DELETE FROM` without WHERE
   - `git push --force` to main/master
   - Commands that affect production systems

2. **NEVER commit credentials or secrets**:
   - API keys, passwords, tokens
   - .env files with real values
   - Private keys or certificates

3. **NEVER bypass safety checks**:
   - Skip pre-commit hooks (--no-verify)
   - Disable linting or type checking
   - Ignore test failures

4. **STAY within scope**:
   - Only modify files related to the assigned task
   - Do not make changes to unrelated systems
   - Do not access resources outside the workspace

---

## ESCALATION TRIGGERS

STOP and escalate to human when:

- Same error occurs 3+ times with same fix
- Changes would affect 10+ files
- Merge conflicts that cannot be resolved automatically
- Any security-related code changes
- Database schema modifications
- Changes to authentication/authorization

---

## VERIFICATION REQUIREMENTS

Before completing any task:

1. Run quality checks (lint, type, test)
2. Verify no secrets in staged changes
3. Confirm changes are within blast radius limits
4. Ensure all tests pass

---

## WORKSPACE BOUNDARIES

- Work only in assigned worktree
- Do not modify main branch directly
- Create PRs for review, do not auto-merge
- Preserve worktree on failure for human inspection

---

**END SAFETY DIRECTIVE**
