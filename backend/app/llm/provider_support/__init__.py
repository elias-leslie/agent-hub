"""Shared provider support helpers.

Provider modules under ``app.llm.providers`` are import-time registrations.
Helper-only ports live here so architecture checks can enforce exactly one
``register_api_provider`` call per provider module.
"""

