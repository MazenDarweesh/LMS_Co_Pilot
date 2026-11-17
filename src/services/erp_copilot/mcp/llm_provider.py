"""
Chat LLM Provider Factory
=========================
Constructs LangChain chat models across supported providers (`google`, `groq`,
`anthropic`) using environment-backed settings with fail-closed validation and
zero hardcoded secrets.
"""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
import structlog

from src.core.config import settings

logger = structlog.get_logger()

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-5-5"
SUPPORTED_CHAT_PROVIDERS: frozenset[str] = frozenset({"google", "groq", "anthropic"})


class LlmProviderConfigError(ValueError):
    """Raised when an LLM provider is unsupported or missing its required API key."""


def resolve_chat_provider_and_model(
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str, str]:
    """
    Resolves the effective `(provider, model)` pair from explicit overrides or
    configured settings without instantiating any network client.
    """
    raw_provider = settings.CHAT_LLM_PROVIDER if provider is None else provider
    resolved_provider = (raw_provider or "").strip().lower()
    if resolved_provider not in SUPPORTED_CHAT_PROVIDERS:
        raise LlmProviderConfigError(
            f"Unsupported chat LLM provider '{resolved_provider}'. "
            f"Supported providers: {', '.join(sorted(SUPPORTED_CHAT_PROVIDERS))}."
        )

    raw_model = settings.CHAT_LLM_MODEL if model is None else model
    resolved_model = (raw_model or "").strip()
    if not resolved_model:
        if resolved_provider == "google":
            resolved_model = (settings.GEMINI_MODEL or "gemini-3.5-flash-lite").strip()
        elif resolved_provider == "groq":
            resolved_model = DEFAULT_GROQ_MODEL
        elif resolved_provider == "anthropic":
            resolved_model = DEFAULT_ANTHROPIC_MODEL

    return resolved_provider, resolved_model


def _require_api_key(key_value: str | None, env_name: str, provider_name: str) -> str:
    cleaned = (key_value or "").strip()
    if not cleaned:
        raise LlmProviderConfigError(
            f"{env_name} must be configured and non-empty when provider='{provider_name}'."
        )
    return cleaned


def build_chat_model(
    provider: str | None = None,
    model: str | None = None,
    *,
    temperature: float | None = None,
) -> BaseChatModel:
    """
    Builds a LangChain `BaseChatModel` for `google`, `groq`, or `anthropic`.
    Fails closed with `LlmProviderConfigError` on missing API keys or unknown providers.
    """
    resolved_provider, resolved_model = resolve_chat_provider_and_model(
        provider=provider,
        model=model,
    )

    kwargs: dict[str, object] = {"model": resolved_model}
    if temperature is not None:
        kwargs["temperature"] = temperature

    if resolved_provider == "google":
        api_key = _require_api_key(settings.GEMINI_API_KEY, "GEMINI_API_KEY", "google")
        logger.debug("Building Google chat model", provider="google", model=resolved_model)
        return ChatGoogleGenerativeAI(api_key=api_key, **kwargs)

    if resolved_provider == "groq":
        api_key = _require_api_key(settings.GROQ_API_KEY, "GROQ_API_KEY", "groq")
        logger.debug("Building Groq chat model", provider="groq", model=resolved_model)
        return ChatGroq(api_key=api_key, **kwargs)

    api_key = _require_api_key(settings.ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY", "anthropic")
    logger.debug("Building Anthropic chat model", provider="anthropic", model=resolved_model)
    return ChatAnthropic(api_key=api_key, **kwargs)
