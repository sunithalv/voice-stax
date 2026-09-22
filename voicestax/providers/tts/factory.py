# Implementation for TTS provider factory and registry.
from voicestax.providers.tts.elevenlabs import ElevenLabsTTSProvider
from voicestax.utils.exceptions import ProviderNotSupportedError

TTS_PROVIDER_REGISTRY = {
    "elevenlabs": ElevenLabsTTSProvider,
}

# Factory function to get TTS provider instance
def get_tts_provider(provider_name: str, api_key: str, **kwargs):
    """
    Factory for TTS providers.
    Parameters are optional; if not provided, fallback to settings.
    """
    provider_class = TTS_PROVIDER_REGISTRY.get(provider_name.lower())

    if provider_class is None:
        raise ProviderNotSupportedError(
            f"Unsupported TTS provider: {provider_name}"
        )

    provider = provider_class(api_key=api_key, **kwargs)

    provider.validate_api_key()

    return provider
