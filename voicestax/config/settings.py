# Configuration settings for the voice assistant.
# This file defines the VoiceSettings model and helper methods for loading,
# validating, and retrieving provider configuration values such as API keys.

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import Any, Dict, Optional
from voicestax.utils.exceptions import ConfigurationError

SUPPORTED_LANGUAGES = {"en", "hi", "ml"}


class VoiceSettings(BaseSettings):

    app_name: str = "VoiceStax"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # VoiceStax application configuration
    log_level: str = "DEBUG"
    enable_metrics: bool = True

    # First message configuration
    first_speaker: str = "assistant"
    initial_message: str = "Hello! I am your AI assistant."
    language: str = "en"

    # API keys — loaded from .env
    stt_api_key: Optional[str] = None
    llm_api_key: Optional[str] = None
    tts_api_key: Optional[str] = None

    # Provider selection
    stt_provider: str = "assemblyai"
    stt_config: Dict[str, Any] = Field(default_factory=dict)

    llm_provider: str = "groq"
    llm_config: Dict[str, Any] = Field(default_factory=dict)

    tts_provider: str = "elevenlabs"
    tts_config: Dict[str, Any] = Field(default_factory=dict)

    vad_provider: str = "webrtc"
    vad_config: Dict[str, Any] = Field(default_factory=dict)

    # VoiceStax pipeline configuration
    vad_silence_threshold_ms: int = 300
    vad_max_utterance_ms: int = 20_000

    llm_system_prompt: str = Field(
        default=(
            "You are a real-time voice assistant. "
            "Your ENTIRE response must be ONLY a valid JSON object — "
            "no other text, no explanation, no preamble. "
            'Format: {"intent": "conversation|clarification|end_conversation|human_handoff", '
            '"response": "your reply in 1-2 short conversational sentences"}'
        ),
        description=(
            "Core VoiceStax system prompt defining conversational behavior "
            "and the structured LLM response format."
        ),
    )

    llm_timeout_seconds: int = 20

    
    #Validate language field to ensure it is one of the supported languages
    @field_validator("language")
    @classmethod
    def validate_language(cls, v):
        if v not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language: {v}. "
                f"Supported: {SUPPORTED_LANGUAGES}"
            )
        return v

    
    # Get API keys for the selected providers
    def get_api_key(self, provider: str) -> Optional[str]:
        return getattr(self, f"{provider}_api_key", None)

    # Validate that all required API keys are present for the selected providers
    def validate_providers(self):
        errors = []

        if not self.get_api_key("llm"):
            errors.append(f"Missing API key for LLM provider: {self.llm_provider}")

        if not self.get_api_key("stt"):
            errors.append(f"Missing API key for STT provider: {self.stt_provider}")

        if not self.get_api_key("tts"):
            errors.append(
                f"Missing API key for TTS provider: {self.tts_provider}"
            )

        if errors:
            raise ConfigurationError(" | ".join(errors))

    # Strip whitespace from API keys 
    @field_validator("stt_api_key", "llm_api_key", "tts_api_key")
    @classmethod
    def strip_keys(cls, v):
        return v.strip() if isinstance(v, str) else v



# Returns a VoiceSettings instance, either from the override or from defaults
def get_settings(override: Optional[VoiceSettings] = None) -> VoiceSettings:
    #If no override is provided, create a new VoiceSettings instance 
    settings= override or VoiceSettings()
    # Validate the settings to ensure all required API keys are present
    settings.validate_providers()  
    return settings


