"""Tool guidance follows the caller's declared tools or the agent's own registry."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.runtime_context import _compute_auxiliary_blocks


@pytest.mark.asyncio
async def test_external_shell_does_not_depend_on_internal_project_permissions():
    with (
        patch('app.services.runtime_context.get_agent_tool_specs') as registry,
        patch('app.services.runtime_context.decay_score_by_surface', new=AsyncMock(return_value={})),
        patch('app.services.runtime_context.format_tool_capability_context', return_value='<tool-usage>guide</tool-usage>') as render,
    ):
        _, guide, diagnostics = await _compute_auxiliary_blocks(
            consumer_profile='agent_startup', consumer_surface='codex', capabilities=['bash'],
            agent_slug=None, project_id='ominull', task_type='backend',
            include_project_index=False, include_tool_capabilities=True,
        )
    registry.assert_not_called()
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('agent_slug', 'bash_available'),
    [('vantage-research', False), ('governance-auditor', True), ('agent-without-registry', None), (None, None)],
)
async def test_agent_hub_shell_follows_the_agents_own_tool_registry(agent_slug, bash_available):
    with (
        patch('app.services.runtime_context.decay_score_by_surface', new=AsyncMock(return_value={})),
        patch('app.services.runtime_context.format_tool_capability_context', return_value='<tool-usage>guide</tool-usage>') as render,
    ):
        await _compute_auxiliary_blocks(
            consumer_profile='agent_startup', consumer_surface='agent_hub', capabilities=[],
            agent_slug=agent_slug, project_id='ominull', task_type='backend',
            include_project_index=False, include_tool_capabilities=True,
        )
    if bash_available is False:
        render.assert_not_called()
    else:
        assert render.call_args.kwargs['bash_available'] is bash_available
