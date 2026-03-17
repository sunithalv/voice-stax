# VoiceStax/providers/stt/factory.py

from typing import Any
from voicestax.providers.stt.assemblyai import AssemblyAISTTProvider
from voicestax.utils.exceptions import ProviderNotSupportedError, STTValidationError


def get_stt_provider(provider_name: str, **kwargs: Any):
    """
    Factory method to create STT providers dynamically.

    Args:
        provider_name: Name of the STT provider (assemblyai, google, whisper, etc.)
        **kwargs: Provider-specific parameters

    Returns:
        Instance of BaseSTTProvider
    """

    provider_name = provider_name.lower()

    if provider_name == "assemblyai":
        # Remove unsupported param for AssemblyAI
        kwargs.pop("model", None)
        provider = AssemblyAISTTProvider(**kwargs)
        if not provider.validate_api_key():
            raise STTValidationError(f"Invalid API key for STT provider: {provider_name}")
        return provider

    # Future providers can be added here
    # elif provider_name == "google":
    #     from .google import GoogleSTTProvider
    #     return GoogleSTTProvider(**kwargs)

    # elif provider_name == "whisper":
    #     from .whisper import WhisperSTTProvider
    #     return WhisperSTTProvider(**kwargs)

    raise ProviderNotSupportedError(f"Unsupported STT provider: {provider_name}")
