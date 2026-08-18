"""stream_google must feed the key pool so a dead account stops being chosen."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, ClassVar

import pytest

from app.llm import api_key_pool
from app.llm.model_resolver import resolve_llm_model
from app.llm.providers import google
from app.llm.types import Context, SimpleStreamOptions, UserMessage

KEYS = ["dead-key-0001", "live-key-0002"]


@pytest.fixture(autouse=True)
def _pool_with_two_accounts(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    api_key_pool.reset()
    monkeypatch.setattr(google, "get_env_api_keys", lambda _provider: list(KEYS))
    monkeypatch.setattr(google, "get_env_api_key", lambda _provider: KEYS[0])
    yield
    api_key_pool.reset()


def _context() -> Context:
    return Context(messages=[UserMessage(content="hi", timestamp=0)])


class _FakeClient:
    """Stands in for genai.Client, refusing whichever keys the test names."""

    def __init__(self, api_key: str, refuse: dict[str, str], seen: list[str]) -> None:
        self.api_key = api_key
        self._refuse = refuse
        self._seen = seen
        self.aio = self

    @property
    def models(self) -> Any:
        return self

    async def generate_content_stream(self, **_kwargs: Any) -> Any:
        self._seen.append(self.api_key)
        if self.api_key in self._refuse:
            raise RuntimeError(self._refuse[self.api_key])

        async def _stream() -> Any:
            yield _FakeChunk()

        return _stream()


class _FakeChunk:
    candidates: ClassVar[list[Any]] = []
    usage_metadata = None
    response_id = None


def _install_client(monkeypatch: pytest.MonkeyPatch, refuse: dict[str, str]) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(
        google,
        "_create_client",
        lambda _model, api_key, _headers: _FakeClient(api_key, refuse, seen),
    )
    return seen


async def _run(model: Any) -> Any:
    stream = google.stream_simple_google(model, _context(), SimpleStreamOptions())
    return await stream.result()


@pytest.mark.asyncio
async def test_refused_account_is_benched_and_the_next_request_switches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = resolve_llm_model("gemini-2.5-flash-lite", "gemini")
    seen = _install_client(monkeypatch, {KEYS[0]: "429 Your prepayment credits are depleted."})

    first = await _run(model)
    assert first.stop_reason == "error"
    assert seen == [KEYS[0]]

    # The pool learned; nothing else should be sent to the depleted account.
    second = await _run(model)
    assert second.stop_reason == "stop"
    assert seen[1:] == [KEYS[1]]


@pytest.mark.asyncio
async def test_healthy_accounts_are_alternated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quota is per account, so load must not pile onto whichever key is first."""
    model = resolve_llm_model("gemini-2.5-flash-lite", "gemini")
    seen = _install_client(monkeypatch, {})

    for _ in range(4):
        assert (await _run(model)).stop_reason == "stop"

    assert set(seen) == set(KEYS)


@pytest.mark.asyncio
async def test_explicit_api_key_bypasses_the_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    model = resolve_llm_model("gemini-2.5-flash-lite", "gemini")
    seen = _install_client(monkeypatch, {})

    stream = google.stream_simple_google(
        model, _context(), SimpleStreamOptions(api_key="caller-chose-this")
    )
    assert (await stream.result()).stop_reason == "stop"
    assert seen == ["caller-chose-this"]


@pytest.mark.asyncio
async def test_non_key_errors_leave_every_account_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed request fails on every account; benching one would be wrong."""
    model = resolve_llm_model("gemini-2.5-flash-lite", "gemini")
    _install_client(monkeypatch, dict.fromkeys(KEYS, "400 INVALID_ARGUMENT: contents empty"))

    assert (await _run(model)).stop_reason == "error"
    assert api_key_pool._states["gemini"].cooldowns == {}
