"""Base client functionality shared between sync and async clients."""

from pathlib import Path

from agent_hub._utils import get_caller_path
from agent_hub.exceptions import ClientDisabledError


class BaseClientMixin:
    """Mixin providing common client functionality."""

    def __init__(
        self,
        base_url: str = "http://localhost:8003",
        api_key: str | None = None,
        timeout: float = 120.0,
        client_name: str | None = None,
        auto_inject_headers: bool = True,
        client_id: str | None = None,
        request_source: str | None = None,
        cli_command: str | None = None,
    ) -> None:
        """Initialize base client attributes."""
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.auto_inject_headers = auto_inject_headers
        self.client_id = client_id
        self.request_source = request_source
        self.cli_command = cli_command

        # Auto-detect client name from caller if not provided
        if client_name:
            self.client_name = client_name
        else:
            # Use caller's module name as client name
            caller_path = get_caller_path(skip_frames=2)
            if caller_path:
                self.client_name = Path(caller_path).stem
            else:
                self.client_name = "unknown-client"

        # Dormant mode: set when client receives kill switch (403 with retry_after=-1)
        self._disabled = False
        self._disabled_reason: str | None = None

    def is_disabled(self) -> bool:
        """Check if client is in dormant mode due to kill switch."""
        return self._disabled

    def re_enable(self) -> None:
        """Re-enable client after it was disabled by kill switch."""
        self._disabled = False
        self._disabled_reason = None

    def _check_disabled(self) -> None:
        """Check if client is disabled and raise if so."""
        if self._disabled:
            raise ClientDisabledError(
                message=f"Client is disabled: {self._disabled_reason or 'kill switch activated'}",
                blocked_entity=self.client_name,
                reason=self._disabled_reason,
            )

    def _build_base_headers(self) -> dict[str, str]:
        """Build base headers common to all requests."""
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # Auto-inject source headers for usage control
        if self.auto_inject_headers:
            headers["X-Source-Client"] = "agent-hub-sdk"

        # Inject access control headers if credentials provided
        if self.client_id:
            headers["X-Client-Id"] = self.client_id
        if self.request_source:
            headers["X-Request-Source"] = self.request_source

        return headers

    def _inject_tracking_headers(
        self,
        tool_name: str,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Inject X-Tool-Name and X-Source-Path headers for tracking."""
        headers = extra_headers.copy() if extra_headers else {}
        if self.auto_inject_headers:
            # Use cli_command override if set, otherwise use the SDK method name
            headers["X-Tool-Name"] = self.cli_command or tool_name
            caller_path = get_caller_path(skip_frames=3)
            if caller_path:
                headers["X-Source-Path"] = caller_path
        return headers

    def _build_memory_headers(
        self,
        base_headers: dict[str, str],
        scope: str = "global",
        scope_id: str | None = None,
    ) -> dict[str, str]:
        """Build headers for memory operations."""
        headers = base_headers.copy()
        if scope != "global":
            headers["X-Memory-Scope"] = scope
        if scope_id:
            headers["X-Scope-Id"] = scope_id
        return headers
