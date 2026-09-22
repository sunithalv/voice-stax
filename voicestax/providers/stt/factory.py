# STT provider factory for creating speech-to-text implementations.
# It registers supported providers and returns the appropriate provider instance.

from voicestax.providers.stt.assemblyai import AssemblyAISTTProvider
from voicestax.utils.exceptions import ProviderNotSupportedError

STT_PROVIDER_REGISTRY = {
    "assemblyai": AssemblyAISTTProvider,
}


def get_stt_provider(provider_name: str,api_key:str, **kwargs):

    provider_class = STT_PROVIDER_REGISTRY.get(provider_name.lower())

    if provider_class is None:
        raise ProviderNotSupportedError(
            f"Unsupported STT provider: {provider_name}"
        )

    provider = provider_class(api_key=api_key,**kwargs)

    provider.validate_api_key()

    return provider
