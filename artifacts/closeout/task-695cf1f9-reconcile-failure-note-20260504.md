# task-695cf1f9 reconcile failure note

- task: `task-695cf1f9`
- flow: `manage_tasks(action="reconcile")` via SummitFlow `st done`
- failure: `AttributeError: 'STClient' object has no attribute 'get_task_completion_readiness'`
- blocker class: SummitFlow CLI client method/path mismatch, not Agent Hub lane logic

## stack context

Observed path from failure report:

- Agent Hub `manage_tasks(action="reconcile")`
- lane reconcile calls `st done`
- SummitFlow `done_task._auto_verify_readiness()` calls `client.get_task_completion_readiness(task_id)`
- runtime `STClient` object lacks that method
- reconcile aborts before closeout

## repo evidence

Current SummitFlow source already defines method and endpoint path:

- `../summitflow/backend/cli/_client_mixins_tasks.py:118` defines `get_task_completion_readiness(self, task_id)`
- `../summitflow/backend/cli/_client_tasks.py:46` implements GET `/tasks/{task_id}/completion-readiness`
- `../summitflow/backend/cli/commands/done_task.py:74` calls `client.get_task_completion_readiness(task_id)`
- `../summitflow/backend/tests/cli/test_done_task.py:83` verifies `STClient` exposes method

## diagnosis

Failure matches stale or mismatched SummitFlow client composition. Current source includes method. Crash likely came from runtime using older `STClient` class shape, or prior class composition that omitted `_TaskWorkflowMixin` / readiness path.

## follow-through

- Keep note with task closeout evidence.
- If failure reappears in live lane, inspect installed/runtime SummitFlow version versus current repo source before re-diagnosing Agent Hub reconcile.
