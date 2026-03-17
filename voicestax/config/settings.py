# settings.py

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, ValidationError, field_validator
from typing import Optional, Dict
from voicestax.utils.exceptions import ConfigurationError

JSON_STRUCTURE_SUFFIX = (
    "\n\nYour ENTIRE response must be ONLY a valid JSON object — "
    "no other text, no explanation, no preamble. "
    'Format: {"intent": "continue | end_session", '
    '"response": "your reply in 1-2 short conversational sentences"}'
)


class VoiceSettings(BaseSettings):
    """Configuration for VoiceStax voice agent"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

    # First message configuration
    first_speaker: str = "assistant"
    initial_message: str = "Hello! I am your AI assistant."

    # Provider selection
    stt_provider: str = "assemblyai"
    tts_provider: str = "elevenlabs"
    llm_provider: str = "groq"

    # API Keys
    stt_api_key: Optional[str] = None
    llm_api_key: Optional[str] = None
    tts_api_key: Optional[str] = None

    # Backward compatibility
    api_keys: Dict[str, Optional[str]] = Field(default_factory=dict)

    # STT
    stt_model: str = "default"
    stt_sample_rate: int = 16000
    stt_encoding: str = "pcm_s16le"

    # TTS
    tts_model: str = "eleven_turbo_v2_5"
    tts_output_format: str = "mp3_22050_32"
    tts_sample_rate: int = 24000
    tts_optimize_latency: int = 3
    tts_voice_id: str = "EXAVITQu4vr4xnSDxMaL"

    # LLM
    llm_model: str = "llama-3.3-70b-versatile"
    llm_max_tokens: int = 120
    llm_system_prompt: str = Field(
        default=(
            "You are a real-time voice assistant. "
            "Your ENTIRE response must be ONLY a valid JSON object — "
            "no other text, no explanation, no preamble. "
            'Format: {"intent": "continue | end_session", '
            '"response": "your reply in 1-2 short conversational sentences"}'
        ),
        description="Override via LLM_SYSTEM_PROMPT in .env to customise assistant behaviour"
    )
    
    @field_validator("llm_system_prompt")
    @classmethod
    def append_json_structure(cls, v: str) -> str:
        # Avoid double-appending if already present
        if JSON_STRUCTURE_SUFFIX.strip() not in v:
            return v + JSON_STRUCTURE_SUFFIX
        return v

    def get_api_key(self, provider: str) -> Optional[str]:
        key = getattr(self, f"{provider}_api_key", None)
        if key:
            return key
        return self.api_keys.get(provider)

    def validate_providers(self):
        errors = []

        if not self.get_api_key("llm"):
            errors.append(f"Missing API key for LLM provider: {self.llm_provider}")

        if not self.get_api_key("stt"):
            errors.append(f"Missing API key for STT provider: {self.stt_provider}")

        if self.tts_provider and not self.get_api_key("tts"):
            from voicestax.utils.logger import logger
            logger.warning(
                f"TTS provider '{self.tts_provider}' has no API key. TTS will be disabled."
            )

        if errors:
            raise ConfigurationError(" | ".join(errors))

    @field_validator("stt_api_key", "llm_api_key", "tts_api_key")
    def strip_keys(cls, v):
        return v.strip() if isinstance(v, str) else v


# Lazy global instance — only created on first call, not at import time
_global_settings: Optional[VoiceSettings] = None


def get_settings(override: Optional[VoiceSettings] = None) -> VoiceSettings:
    """
    Returns a VoiceSettings instance.
    - If `override` is passed (programmatic config), use it directly.
    - Otherwise, lazily load from .env once and cache it globally.
    """
    if override:
        # Always validate explicitly-passed settings so the user gets
        # clear errors if they forget an API key
        override.validate_providers()
        return override

    global _global_settings
    if _global_settings is None:
        try:
            _global_settings = VoiceSettings()
            _global_settings.validate_providers()
        except (ValidationError, ValueError) as e:
            raise ConfigurationError(f"Configuration error: {e}") from e

    return _global_settings

