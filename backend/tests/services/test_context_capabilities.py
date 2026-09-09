"""External tool guidance follows declared tools, not internal-agent permissions."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.runtime_context import _compute_auxiliary_blocks


@pytest.mark.asyncio
async def test_external_shell_does_not_depend_on_internal_project_permissions():
    with (
        patch('app.services.runtime_context.get_visible_tools_for_project', new_callable=AsyncMock) as permissions,
        patch('app.services.runtime_context.decay_score_by_surface', new=AsyncMock(return_value={})),
        patch('app.services.runtime_context.format_tool_capability_context', return_value='<tool-usage>guide</tool-usage>') as render,
    ):
        _, guide, diagnostics = await _compute_auxiliary_blocks(
            consumer_profile='agent_startup', consumer_surface='codex', capabilities=['bash'],
            agent_slug=None, project_id='ominull', task_type='backend',
            include_project_index=False, include_tool_capabilities=True,
        )
    permissions.assert_not_called()
    assert render.call_args.kwargs['bash_available'] is True
    assert guide == '<tool-usage>guide</tool-usage>'
    assert diagnostics[-1].state == 'included'


@pytest.mark.asyncio
async def test_absent_external_shell_is_explained_without_running_manifest():
    with patch('app.services.runtime_context.format_tool_capability_context') as render:
        _, guide, diagnostics = await _compute_auxiliary_blocks(
            consumer_profile='agent_startup', consumer_surface='mcp', capabilities=[],
            agent_slug=None, project_id='ominull', task_type='backend',
            include_project_index=False, include_tool_capabilities=True,
        )
    render.assert_not_called()
    assert guide == ''
    assert diagnostics[-1].state == 'inapplicable'
    assert diagnostics[-1].reason == 'shell_unavailable'
