Use the Agent tool exactly once to delegate a bounded read-only task.

The child should inspect:
- `/srv/workspaces/projects/agent-hub/backend/app/adapters/claude.py`
- `/srv/workspaces/projects/agent-hub/backend/app/adapters/claude_tools_helpers.py`

Constraints:
- No file edits
- No network
- The top-level assistant must delegate once and then return structured output
