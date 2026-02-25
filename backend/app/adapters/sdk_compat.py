"""Claude Agent SDK compatibility patches.

The SDK's parse_message() raises MessageParseError on unrecognised message
types (e.g. rate_limit_event added by the API after SDK v0.1.39 was released).
This crashes both the streaming and non-streaming completion paths.

This module patches parse_message at the module level so unknown types are
logged and returned as SystemMessage instead of raising. Import this module
before any SDK usage to activate the patch.
"""

import logging
from typing import Any

_logger = logging.getLogger(__name__)
_patched = False


def patch() -> None:
    """Patch Claude Agent SDK message parser to tolerate unknown types."""
    global _patched  # noqa: PLW0603
    if _patched:
        return

    try:
        from claude_agent_sdk._errors import MessageParseError
        from claude_agent_sdk._internal import message_parser
        from claude_agent_sdk.types import SystemMessage

        from claude_agent_sdk.types import Message as SDKMessage

        _original = message_parser.parse_message

        def _tolerant_parse(data: dict[str, Any]) -> SDKMessage:
            try:
                return _original(data)
            except MessageParseError:
                msg_type = data.get("type", "unknown")
                _logger.debug("Skipping unrecognised SDK message type: %s", msg_type)
                return SystemMessage(subtype=msg_type, data=data)

        message_parser.parse_message = _tolerant_parse  # type: ignore[invalid-assignment]

        # Also patch modules that captured a direct reference via
        # `from .message_parser import parse_message` at module level.
        # Without this, their local binding still points to the original.
        import sys
        for mod_name in list(sys.modules):
            if "claude_agent_sdk" not in mod_name or mod_name == message_parser.__name__:
                continue
            mod = sys.modules[mod_name]
            if getattr(mod, "parse_message", None) is _original:
                mod.parse_message = _tolerant_parse  # type: ignore[attr-defined]

        _patched = True
    except ImportError:
        pass  # SDK not installed
