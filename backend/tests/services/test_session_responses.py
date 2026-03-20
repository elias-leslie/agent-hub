"""Tests for session response helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.session_responses import _resolve_agent_display_names


class TestResolveAgentDisplayNames:
    @pytest.mark.asyncio
    async def test_prefers_persona_display_name_from_persona_row(self) -> None:
        events = [
            SimpleNamespace(agent_id="persona", agent_name=None),
            SimpleNamespace(agent_id="coder", agent_name="coder"),
        ]
        agent_rows = MagicMock()
        agent_rows.all.return_value = [
            SimpleNamespace(slug="persona", name="Legacy Persona"),
            SimpleNamespace(slug="coder", name="Coder"),
        ]
        persona_name = MagicMock()
        persona_name.scalar_one_or_none.return_value = "Renamed Persona"

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[agent_rows, persona_name])

        result = await _resolve_agent_display_names(db, events)

        assert result["persona"] == "Renamed Persona"
        assert result["coder"] == "Coder"
