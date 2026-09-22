"""Factory and registry for VAD providers."""
from voicestax.providers.vad.webrtc import WebRTCVAD
from voicestax.utils.exceptions import ProviderNotSupportedError

VAD_PROVIDER_REGISTRY = {
    "webrtc": WebRTCVAD,
}

# Factory function to get VAD provider instance
def get_vad_provider(provider_name: str, **kwargs):
    """
    Factory for VAD providers.
    Parameters are optional; if not provided, fallback to settings.
    """
    provider_class = VAD_PROVIDER_REGISTRY.get(provider_name.lower())

    if provider_class is None:
        raise ProviderNotSupportedError(
            f"Unsupported VAD provider: {provider_name}"
        )

    provider = provider_class(**kwargs)

    return provider
