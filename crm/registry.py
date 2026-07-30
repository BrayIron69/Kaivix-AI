"""
CRM provider selection.

Mirrors utils/llm_provider.py so both config fields behave the same way.
crm_provider in providers.yaml was validated and then ignored -- LeadService
hardcoded SQLiteCRM(). This is the seam that makes it mean something.

crm/hubspot.py and crm/gohighlevel.py exist but are empty files, so "sqlite"
is the only registered provider today. Adding one is: implement BaseCRM in
full, call register_crm_provider(), done -- no edit to LeadService or
ConversationEngine.
"""

from __future__ import annotations

from crm.base_crm import BaseCRM


class UnknownCRMProviderError(Exception):
    """
    Raised when providers.yaml names a crm_provider with no implementation.

    Fatal rather than falling back to SQLite: silently writing a business's
    leads somewhere other than where its config says is worse than
    refusing to start.
    """


_REGISTRY: dict[str, type[BaseCRM]] = {}
_builtins_loaded = False


def register_crm_provider(name: str, provider_cls: type[BaseCRM]) -> None:
    if not issubclass(provider_cls, BaseCRM):
        raise TypeError(
            f"{provider_cls.__name__} must subclass BaseCRM to be "
            f"registered as a CRM provider"
        )
    _REGISTRY[name.strip().lower()] = provider_cls


def _ensure_builtins_registered() -> None:
    """Lazy import: crm.sqlite_crm imports from this package's siblings."""
    global _builtins_loaded
    if _builtins_loaded:
        return

    from crm.sqlite_crm import SQLiteCRM

    register_crm_provider("sqlite", SQLiteCRM)
    _builtins_loaded = True


def available_crm_providers() -> list[str]:
    _ensure_builtins_registered()
    return sorted(_REGISTRY)


def get_crm_provider_class(name: str) -> type[BaseCRM]:
    _ensure_builtins_registered()

    key = (name or "").strip().lower()
    if key not in _REGISTRY:
        raise UnknownCRMProviderError(
            f"unknown crm_provider {name!r} -- "
            f"registered providers: {', '.join(sorted(_REGISTRY)) or '(none)'}"
        )
    return _REGISTRY[key]


def get_crm_provider(name: str) -> BaseCRM:
    """Build the CRM named in business_config.providers.crm_provider."""
    return get_crm_provider_class(name)()
