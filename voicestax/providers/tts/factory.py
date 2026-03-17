from voicestax.config.settings import get_settings
from voicestax.providers.tts.elevenlabs import ElevenLabsTTSProvider
from voicestax.utils.exceptions import ProviderNotSupportedError, TTSValidationError


def get_tts_provider(
    provider_name: str = None,
    api_key: str = None,
    voice_id: str = None,
    model_id: str = None,
    output_format: str = None,
    optimize_latency: bool = None
):
    """
    Factory for TTS providers.
    Parameters are optional; if not provided, fallback to settings.
    """
    settings = get_settings()
    provider_name = provider_name or settings.tts_provider
    key = api_key or settings.tts_api_key

    if provider_name == "elevenlabs":
        provider = ElevenLabsTTSProvider(
            api_key=key,
            voice_id=voice_id,
            model_id=model_id,
            output_format=output_format ,
            optimize_latency=optimize_latency ,
        )
        provider.validate_api_key()  # This will raise appropriate exceptions
        return provider

    raise ProviderNotSupportedError(f"Unsupported TTS provider: {provider_name}")