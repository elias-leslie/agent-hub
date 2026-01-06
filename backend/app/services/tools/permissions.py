"""Permission model for tool execution."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.services.tools.base import PreToolUseHook, ToolCall, ToolDecision


class PermissionMode(Enum):
    """Global permission mode."""

    YOLO = "yolo"  # Auto-approve all tools
    ASK = "ask"  # Require confirmation for each tool
    GRANULAR = "granular"  # Use per-tool rules


@dataclass
class ToolPermission:
    """Permission settings for a specific tool."""

    name: str
    allowed: bool = True
    requires_confirmation: bool = False

    def get_decision(self) -> ToolDecision:
        """Get decision for this tool's permission."""
        if not self.allowed:
            return ToolDecision.DENY
        if self.requires_confirmation:
            return ToolDecision.ASK
        return ToolDecision.ALLOW


@dataclass
class PermissionConfig:
    """
    Permission configuration for tool execution.

    Supports three modes:
    - YOLO: Auto-approve all tools without asking
    - ASK: Require user confirmation for every tool
    - GRANULAR: Check per-tool allow/deny lists

    Per-tool overrides take precedence in all modes.
    """

    mode: PermissionMode = PermissionMode.YOLO
    tool_permissions: dict[str, ToolPermission] = field(default_factory=dict)
    allow_list: set[str] = field(default_factory=set)
    deny_list: set[str] = field(default_factory=set)

    def add_tool_permission(self, permission: ToolPermission) -> None:
        """Add or update a tool-specific permission."""
        self.tool_permissions[permission.name] = permission

    def allow_tool(self, name: str) -> None:
        """Add a tool to the allow list."""
        self.allow_list.add(name)
        self.deny_list.discard(name)

    def deny_tool(self, name: str) -> None:
        """Add a tool to the deny list."""
        self.deny_list.add(name)
        self.allow_list.discard(name)

    def get_decision(self, tool_call: ToolCall) -> ToolDecision:
        """
        Get permission decision for a tool call.

        Priority:
        1. Per-tool permissions (if defined)
        2. Deny list
        3. Allow list
        4. Global mode

        Args:
            tool_call: The tool call to check

        Returns:
            ToolDecision indicating whether to proceed
        """
        name = tool_call.name

        # 1. Check per-tool permissions first
        if name in self.tool_permissions:
            return self.tool_permissions[name].get_decision()

        # 2. Check deny list
        if name in self.deny_list:
            return ToolDecision.DENY

        # 3. Check allow list (in granular mode, allow list grants permission)
        if self.mode == PermissionMode.GRANULAR and name in self.allow_list:
            return ToolDecision.ALLOW

        # 4. Apply global mode
        if self.mode == PermissionMode.YOLO:
            return ToolDecision.ALLOW
        elif self.mode == PermissionMode.ASK:
            return ToolDecision.ASK
        else:  # GRANULAR mode, tool not in any list
            return ToolDecision.ASK

    @classmethod
    def yolo(cls) -> "PermissionConfig":
        """Create a YOLO mode config (auto-approve everything)."""
        return cls(mode=PermissionMode.YOLO)

    @classmethod
    def ask_all(cls) -> "PermissionConfig":
        """Create an ASK mode config (confirm everything)."""
        return cls(mode=PermissionMode.ASK)

    @classmethod
    def granular(
        cls,
        allow: list[str] | None = None,
        deny: list[str] | None = None,
    ) -> "PermissionConfig":
        """
        Create a granular config with allow/deny lists.

        Args:
            allow: Tools to auto-approve
            deny: Tools to deny

        Returns:
            PermissionConfig in granular mode
        """
        return cls(
            mode=PermissionMode.GRANULAR,
            allow_list=set(allow or []),
            deny_list=set(deny or []),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize config to dict for storage."""
        return {
            "mode": self.mode.value,
            "tool_permissions": {
                name: {
                    "name": perm.name,
                    "allowed": perm.allowed,
                    "requires_confirmation": perm.requires_confirmation,
                }
                for name, perm in self.tool_permissions.items()
            },
            "allow_list": list(self.allow_list),
            "deny_list": list(self.deny_list),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PermissionConfig":
        """Deserialize config from dict."""
        config = cls(
            mode=PermissionMode(data.get("mode", "yolo")),
            allow_list=set(data.get("allow_list", [])),
            deny_list=set(data.get("deny_list", [])),
        )
        for _name, perm_data in data.get("tool_permissions", {}).items():
            config.add_tool_permission(
                ToolPermission(
                    name=perm_data["name"],
                    allowed=perm_data.get("allowed", True),
                    requires_confirmation=perm_data.get("requires_confirmation", False),
                )
            )
        return config


class PermissionChecker:
    """
    Permission checker that creates pre-hook callbacks.

    Use with tool handlers to enforce permission rules.
    """

    def __init__(self, config: PermissionConfig):
        """
        Initialize permission checker.

        Args:
            config: Permission configuration to use
        """
        self._config = config

    @property
    def config(self) -> PermissionConfig:
        """Get the current permission config."""
        return self._config

    def update_config(self, config: PermissionConfig) -> None:
        """Update the permission config."""
        self._config = config

    async def check(self, tool_call: ToolCall) -> ToolDecision:
        """
        Check permission for a tool call.

        This method is suitable for use as a pre_hook callback.

        Args:
            tool_call: The tool call to check

        Returns:
            ToolDecision indicating whether to proceed
        """
        return self._config.get_decision(tool_call)

    def create_hook(self) -> "PreToolUseHook":
        """
        Create a pre-hook callback function.

        Returns:
            Async callable suitable for ToolHandler.pre_hook
        """
        return self.check
