"""Provider routing registry.

This module keeps provider-name validation and model-to-provider lookup out of
``app.adapters``. The pi-mono provider registry lives in ``app.llm``; this file
is only for Agent Hub routing and credential surfaces that still speak legacy
provider names such as ``claude`` or ``gemini``.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator

from app.constants.models import PROVIDER_NAMES

CREDENTIAL_ONLY_PROVIDERS = frozenset({"typesafe"})
UNKNOWN_PROVIDER = "unknown"


def get_provider_for_model(model: str) -> str:
    """Return the catalog provider for ``model``, or an explicit known-provider prefix."""
    from app.constants.catalog import (
        INACTIVE_MODEL_CATALOG_BY_ID,
        MODEL_CATALOG_BY_ID,
        resolve_model,
    )

    resolved = resolve_model(model)
    entry = MODEL_CATALOG_BY_ID.get(resolved) or INACTIVE_MODEL_CATALOG_BY_ID.get(resolved)
    if entry:
        return entry.provider

    # Uncatalogued ids route only by an explicit known-provider prefix; the
    # catalog, not string guessing, decides everything else.
    prefix, separator, _ = resolved.partition("/")
    if separator and prefix in PROVIDER_NAMES:
        return prefix
    return UNKNOWN_PROVIDER


def list_providers() -> list[str]:
    """Return provider names visible in the model catalog."""
    from app.constants.catalog import MODEL_CATALOG

    return sorted({entry.provider for entry in MODEL_CATALOG})


def is_workload_provider(provider: str) -> bool:
    """Return whether Agent Hub may execute workloads through ``provider``."""
    return provider not in CREDENTIAL_ONLY_PROVIDERS


def is_workload_model(model: str) -> bool:
    """Return whether Agent Hub may execute workloads through ``model``."""
    return is_workload_provider(get_provider_for_model(model))


def list_workload_providers() -> list[str]:
    """Return catalog providers that are routable for Agent Hub workloads."""
    return [provider for provider in list_providers() if is_workload_provider(provider)]


def list_credential_providers() -> list[str]:
    """Return catalogued providers, including those whose models are all inactive.

    A provider with only inactive rows (an unfunded subscription, say) still
    accepts a credential, so topping it up needs no catalog or code change.
    """
    from app.constants.catalog import INACTIVE_MODEL_CATALOG_BY_ID

    inactive = {entry.provider for entry in INACTIVE_MODEL_CATALOG_BY_ID.values()}
    return sorted(set(list_workload_providers()) | inactive | CREDENTIAL_ONLY_PROVIDERS)


def _validate_provider(v: str) -> str:
    if v not in set(list_providers()):
        raise ValueError(
            f"Unknown provider: {v!r}. Valid providers: {list_providers()}"
        )
    return v


ValidProvider = Annotated[str, BeforeValidator(_validate_provider)]


def _validate_workload_provider(v: str) -> str:
    if not is_workload_provider(v):
        raise ValueError(
            f"Provider {v!r} is credential-only and cannot execute Agent Hub workloads"
        )
    return _validate_provider(v)


ValidWorkloadProvider = Annotated[str, BeforeValidator(_validate_workload_provider)]


__all__ = [
    "CREDENTIAL_ONLY_PROVIDERS",
    "UNKNOWN_PROVIDER",
    "ValidProvider",
    "ValidWorkloadProvider",
    "get_provider_for_model",
    "is_workload_model",
    "is_workload_provider",
    "list_credential_providers",
    "list_providers",
    "list_workload_providers",
]
