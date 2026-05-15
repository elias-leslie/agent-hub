import pytest

from app.services.tools._executor_io_lanes import _dispatch_done


class _Session:
    def __init__(self, status='completed', workstream_status=None):
        self.status = status
        self.workstream_status = workstream_status


@pytest.mark.asyncio
async def test_dispatch_done_retries_admin_for_dirty_checkout_block():
    calls = []

    async def bash_fn(cmd: str) -> str:
        calls.append(cmd)
        if '--admin' in cmd:
            return 'Closed via admin path'
        return 'Claimed checkout has uncommitted changes.'

    result = await _dispatch_done(
        bash_fn,
        'task-a2178df4',
        'agent-hub',
        'msg',
        [_Session()],
    )

    assert result == 'Closed via admin path'
    assert len(calls) == 2
    assert '--admin' in calls[1]


@pytest.mark.asyncio
async def test_dispatch_done_preserves_unknown_readiness_failure():
    async def bash_fn(cmd: str) -> str:
        return 'Task not ready to complete: unknown'

    result = await _dispatch_done(
        bash_fn,
        'task-c4fbbd9d',
        'agent-hub',
        'msg',
        [_Session()],
    )

    assert 'SummitFlow reported the task is not ready to complete' in result
    assert 'Task not ready to complete: unknown' in result
