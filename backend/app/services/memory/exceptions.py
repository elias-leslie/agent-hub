"""Memory service exception types for specific error handling."""

from __future__ import annotations


class MemoryServiceError(Exception):
    """Base exception for memory service operations."""


class DedupError(MemoryServiceError):
    """Error during content deduplication."""


class PromotionError(MemoryServiceError):
    """Error during learning promotion or reinforcement."""


class MemoryConnectionError(MemoryServiceError):
    """Error connecting to memory backend (PostgreSQL + pgvector)."""
