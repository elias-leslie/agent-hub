"""Step test hooks the engine lets through only while ``workflow_test_hooks_enabled`` is on.

An injected refusal ends the attempt exactly as a provider refusal would (the executor feeds its own
refusal record through its normal outcome path); no provider's safety classifier is contacted.
"""

from __future__ import annotations

from dataclasses import dataclass

from .packet import HandoffPacket


@dataclass(frozen=True)
class RefusalHook:
    after_turn: int
    category: str

    def due(self, turns: int) -> bool:
        return turns >= self.after_turn


def refusal_hook(packet: HandoffPacket) -> RefusalHook | None:
    hooks = packet.test_hooks or {}
    after = hooks.get("refuse_after_turn")
    if not isinstance(after, int) or after < 1:
        return None
    return RefusalHook(after, str(hooks.get("refusal_category") or "cyber"))
