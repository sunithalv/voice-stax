from voicestax.config.settings import get_settings
from voicestax.providers.llm.groq import GroqLLMProvider
from voicestax.utils.exceptions import ProviderNotSupportedError, LLMValidationError


def get_llm_provider(
    provider_name: str = None,
    api_key: str = None,
    model: str = None,
    max_tokens: int = None
):
    settings = get_settings()

    provider_name = provider_name or settings.llm_provider

    if provider_name == "groq":
        # Use the passed api_key or fallback to settings
        key = api_key or settings.llm_api_key
        provider = GroqLLMProvider(api_key=key, model=model, max_tokens=max_tokens)
        provider.validate_api_key()  # This will raise appropriate exceptions
        return provider

    raise ProviderNotSupportedError(f"Unsupported LLM provider: {provider_name}")
