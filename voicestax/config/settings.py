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
    log_level: str = "INFO"
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
    vad_silence_threshold_ms: int = 800
    vad_max_utterance_ms: int = 20_000

    llm_system_prompt: str = Field(
        default=(
            "You are a real-time voice assistant. "

            "OUTPUT FORMAT: "
            "Return exactly one valid JSON object with exactly two fields: "
            '"intent" and "response". '
            'The "intent" must be one of: conversation, clarification, '
            "end_conversation, human_handoff. "
            'The "response" must be a string containing the spoken reply. '
            "Return JSON only, with no markdown or text outside the object. "
            "Do not call tools or functions, and do not wrap the object in "
            'any other structure such as "name" or "arguments". '
            "Ensure all JSON strings are properly escaped. "

            "CONVERSATION: "
            "Use conversation history to understand the user's meaning, "
            "including short replies such as yes, no, fine, and okay. "
            "Respond helpfully and naturally. "
            "Keep the conversation going: after answering or explaining "
            "something, end with one short, relevant follow-up question "
            "or offer, such as a related subtopic the user might want "
            "to explore next. Vary the follow-ups and do not repeat "
            "questions already answered. "
            "Never invent facts or user intentions. "
            "Ask for clarification when the meaning is genuinely unclear. "
            "Short acknowledgements such as good, okay, nice, cool, "
            "great, or thanks are NOT a request to end the conversation; "
            "treat them as conversation and continue with a relevant "
            "next step or question. "
            "Use end_conversation only when the user explicitly says "
            "goodbye or clearly states they want to stop. "
            "Use human_handoff when a human handoff "
            "is appropriate and supported by the application. "

            "VOICE STYLE: "
            "The response string will be sent directly to text-to-speech. "
            "Use natural spoken language, short sentences, and simple "
            "punctuation. Avoid markdown, lists, emojis, and decorative "
            "symbols. Normally keep the spoken reply to one or two "
            "short sentences. "
            "Answer the user's actual request before adding a follow-up."
        ),
        description=(
            "Core VoiceStax system prompt defining conversational "
            "behaviour and structured LLM output."
        ),
    )


    llm_timeout_seconds: int = 20

    # Fallbacks used when the LLM does not return the required
    # {"intent", "response"} JSON, whichever provider is used.
    # 1) Retry once, asking the model to reformat its reply as JSON.
    llm_json_retry: bool = True
    # 2) If that also fails, guess the intent from the user's words.
    intent_keyword_fallback: bool = True
    # Only short user messages are matched, to avoid false positives.
    intent_keyword_max_words: int = 8

    # Single source of truth for goodbye / handoff phrases. Used by:
    #  - the local intent check (whole utterance must equal a phrase, no
    #    LLM call), and
    #  - the keyword fallback (phrase inside a short message) when the
    #    LLM returns no intent.
    # Keep ambiguous phrases such as "that's it" or "thanks" out of these
    # lists; those need context and are left to the LLM.
    end_conversation_phrases: list[str] = Field(
        default_factory=lambda: [
            "bye", "bye bye", "goodbye", "good bye", "see you",
            "see you later", "talk to you later", "have a good day",
            "have a nice day", "thanks bye", "thank you bye",
            "you can end the call", "end the call",
            "end the conversation", "stop the conversation",
            "i have to go", "i need to go",
        ]
    )
    human_handoff_phrases: list[str] = Field(
        default_factory=lambda: [
            "connect me to a human", "connect me to an agent",
            "speak to a human", "speak to an agent", "talk to a human",
            "talk to an agent", "transfer me to an agent",
            "i want a human", "talk to a person", "speak to a person",
            "real person", "human agent",
        ]
    )

    
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


