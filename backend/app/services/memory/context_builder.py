"""Tier-aware context builder for mandates, guardrails, and direct references."""

from __future__ import annotations

from .context_builder_ops import ProgressiveContext, build_progressive_context


def get_loaded_uuids(context: ProgressiveContext) -> list[str]:
    return context.get_loaded_uuids()


def get_mandate_uuids(context: ProgressiveContext) -> list[str]:
    return context.get_mandate_uuids()


def get_guardrail_uuids(context: ProgressiveContext) -> list[str]:
    return context.get_guardrail_uuids()


def get_reference_uuids(context: ProgressiveContext) -> list[str]:
    return context.get_reference_uuids()


def get_reference_index_uuids(context: ProgressiveContext) -> list[str]:
    return context.get_reference_index_uuids()

__all__ = [
    "ProgressiveContext",
    "build_progressive_context",
    "get_guardrail_uuids",
    "get_loaded_uuids",
    "get_mandate_uuids",
    "get_reference_index_uuids",
    "get_reference_uuids",
]
