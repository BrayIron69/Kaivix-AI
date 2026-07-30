"""
LLM provider selection.

config/businesses/<id>/providers.yaml has always carried an llm_provider
field, and BusinessConfig validated it, but nothing ever read it -- every
business got Groq regardless. This module is the seam that makes the field
mean something.

The contract is deliberately one method. ConversationEngine only ever calls
generate(messages), so that is the entire surface a second provider has to
implement. Adding one is: subclass BaseLLMProvider, call
register_llm_provider(), done -- no edit to ConversationEngine.

Provider-specific exceptions must NOT escape an implementation. Translate
them to utils.exceptions.LLMUnavailableError so callers stay
vendor-agnostic (see utils/llm.py for how the Groq one does it).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class UnknownLLMProviderError(Exception):
    """
    Raised when providers.yaml names an llm_provider with no implementation.

    Deliberately fatal at construction rather than falling back to Groq: a
    typo in a business's config silently serving a different provider than
    the one written down is worse than refusing to start.
    """


class BaseLLMProvider(ABC):
    """The one method ConversationEngine depends on."""

    @abstractmethod
    def generate(self, messages: list[dict]) -> str:
        """
        Send a standard chat message list, return the assistant's text.

        Raises
        ------
        LLMUnavailableError
            If the provider is unreachable or refuses the request.
        """


_REGISTRY: dict[str, type[BaseLLMProvider]] = {}
_builtins_loaded = False


def register_llm_provider(name: str, provider_cls: type[BaseLLMProvider]) -> None:
    """
    Register an implementation under the name used in providers.yaml.

    Names are matched case-insensitively and stripped, so "Groq" and "groq "
    in a hand-edited YAML file both resolve.
    """
    if not issubclass(provider_cls, BaseLLMProvider):
        raise TypeError(
            f"{provider_cls.__name__} must subclass BaseLLMProvider to be "
            f"registered as an LLM provider"
        )
    _REGISTRY[name.strip().lower()] = provider_cls


def _ensure_builtins_registered() -> None:
    """
    Import and register the implementations that ship with the project.

    Imported lazily, inside the function, because utils/llm.py imports this
    module for the base class -- a module-level import here would be
    circular.
    """
    global _builtins_loaded
    if _builtins_loaded:
        return

    from utils.llm import LLM

    register_llm_provider("groq", LLM)
    _builtins_loaded = True


def available_llm_providers() -> list[str]:
    """Registered provider names, for error messages and tests."""
    _ensure_builtins_registered()
    return sorted(_REGISTRY)


def get_llm_provider_class(name: str) -> type[BaseLLMProvider]:
    """Resolve a providers.yaml name to its class without instantiating."""
    _ensure_builtins_registered()

    key = (name or "").strip().lower()
    if key not in _REGISTRY:
        raise UnknownLLMProviderError(
            f"unknown llm_provider {name!r} -- "
            f"registered providers: {', '.join(sorted(_REGISTRY)) or '(none)'}"
        )
    return _REGISTRY[key]


def get_llm_provider(name: str) -> BaseLLMProvider:
    """
    Build the provider named in providers.yaml.

    Parameters
    ----------
    name : str
        The value of business_config.providers.llm_provider.
    """
    return get_llm_provider_class(name)()
