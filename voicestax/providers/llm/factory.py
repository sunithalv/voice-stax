"""
LLM provider factory for VoiceStax.

This module:
- Registers supported LLM providers.
- Selects a provider by name.
- Instantiates the provider with the supplied API key and configuration.
- Validates the provider API key before returning the instance.
"""

from voicestax.providers.llm.groq import GroqLLMProvider
from voicestax.utils.exceptions import (
    LLMValidationError,
    ProviderNotSupportedError,
)


LLM_PROVIDER_REGISTRY = {
    "groq": GroqLLMProvider,
}


def get_llm_provider(
    provider_name: str,
    api_key: str,
    **kwargs,
):
    """
    Create and return the requested LLM provider.

    Example:

        provider = get_llm_provider(
            provider_name="groq",
            api_key=settings.llm_api_key,
            model="llama-3.3-70b-versatile",
            max_tokens=120,
            temperature=0.2,
        )

    Additional kwargs are passed directly to the selected provider.
    """

    if not provider_name:
        raise ProviderNotSupportedError(
            "LLM provider name is required"
        )

    provider_class = LLM_PROVIDER_REGISTRY.get(
        provider_name.lower()
    )

    if provider_class is None:
        raise ProviderNotSupportedError(
            f"Unsupported LLM provider: {provider_name}"
        )

    # Pass the API key explicitly and forward all provider-specific
    # configuration parameters unchanged.
    provider = provider_class(
        api_key=api_key,
        **kwargs,
    )

    # This validates the key/provider configuration according to the
    # implementation of the selected provider.
    if not provider.validate_api_key():
        raise LLMValidationError(
            "Invalid or missing API key for LLM provider: "
            f"{provider_name}"
        )

    return provider