"""Provider-owned runtime sessions for tool/event turns."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


class ProviderRuntimeSession(ABC):
    """Canonical provider runtime session boundary for one active turn."""

    @abstractmethod
    def events(self) -> AsyncIterator[tuple[Any, str | None]]:
        """Yield canonical runtime events for the active turn."""

    async def interrupt(self) -> None:
        """Interrupt the active turn."""
        await self.close()

    async def respond_to_request(
        self,
        *,
        request_id: str,
        decision: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Respond to a provider approval request."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support request responses",
        )

    async def respond_to_user_input(
        self,
        *,
        request_id: str,
        response: str,
    ) -> None:
        """Respond to a provider user-input request."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support structured user input",
        )

    @abstractmethod
    async def close(self) -> None:
        """Close the active turn session."""


@dataclass
class StreamBackedRuntimeSession(ProviderRuntimeSession):
    """Runtime session backed by an async event stream."""

    stream: AsyncIterator[tuple[Any, str | None]]
    interrupt_callback: Callable[[], Awaitable[None]] | None = None
    close_callback: Callable[[], Awaitable[None]] | None = None
    _closed: bool = field(default=False, init=False)

    def events(self) -> AsyncIterator[tuple[Any, str | None]]:
        """Return the owned event stream."""
        return self.stream

    async def interrupt(self) -> None:
        """Interrupt via owned callback when available, else close the stream."""
        if self.interrupt_callback is not None:
            await self.interrupt_callback()
            return
        await self.close()

    async def close(self) -> None:
        """Close the stream once."""
        if self._closed:
            return
        self._closed = True
        if self.close_callback is not None:
            await self.close_callback()
            return
        aclose = getattr(self.stream, "aclose", None)
        if aclose is None:
            return
        await aclose()
