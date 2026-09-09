"""Authoring preserves useful prose instead of enforcing a speaking style."""

import pytest

from app.services.prompt_service import create_prompt
from tests.conftest import create_mock_db_session


@pytest.mark.asyncio
async def test_prompt_preserves_uncertainty_and_examples() -> None:
    content = (
        "A timeout could indicate packet loss. For example, compare the failed "
        "request with a successful request before claiming a cause."
    )
    db = create_mock_db_session()

    prompt = await create_prompt(
        db, slug="network-evidence", name="Network evidence", content=content
    )

    assert prompt.content == content
    assert db.add.call_args_list[1].args[0].content == content
