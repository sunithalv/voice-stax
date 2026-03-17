# VoiceStax/utils/exceptions.py

class VoiceStaxError(Exception):
    """Base class for all VoiceStax exceptions."""
    pass

# ------------------ Configuration Exceptions ----------------
class ConfigurationError(VoiceStaxError):
    """Raised for configuration-related errors."""
    pass

class ProviderInitializationError(VoiceStaxError):
    """Raised when a provider cannot be initialized."""
    pass

class ProviderNotSupportedError(VoiceStaxError):
    """Raised when an unsupported provider is requested."""
    pass

# ------------------ STT Exceptions ----------------
class STTError(VoiceStaxError):
    """Raised for errors in speech-to-text provider."""
    pass

class STTConnectionError(STTError):
    """Raised when STT provider connection fails."""
    pass

class STTStreamingError(STTError):
    """Raised for STT streaming errors."""
    pass

class STTValidationError(STTError):
    """Raised for STT validation errors (e.g., invalid API key)."""
    pass

# ------------------ TTS Exceptions ----------------
class TTSError(VoiceStaxError):
    """Raised for errors in text-to-speech provider."""
    pass

class TTSConnectionError(TTSError):
    """Raised when TTS provider connection fails."""
    pass

class TTSStreamingError(TTSError):
    """Raised for TTS streaming errors."""
    pass

class TTSValidationError(TTSError):
    """Raised for TTS validation errors (e.g., invalid API key)."""
    pass

# ------------------ LLM Exceptions ----------------
class LLMError(VoiceStaxError):
    """Raised for LLM request failures."""
    pass

class LLMConnectionError(LLMError):
    """Raised when LLM provider connection fails."""
    pass

class LLMStreamingError(LLMError):
    """Raised for LLM streaming errors."""
    pass

class LLMValidationError(LLMError):
    """Raised for LLM validation errors (e.g., invalid API key)."""
    pass

# ------------------ Audio Exceptions ----------------
class AudioError(VoiceStaxError):
    """Raised for audio processing errors."""
    pass

class AudioProcessingError(AudioError):
    """Raised when audio processing fails."""
    pass

# ------------------ Session Exceptions ----------------
class SessionError(VoiceStaxError):
    """Raised for session management errors."""
    pass

class SessionStateError(SessionError):
    """Raised for invalid session state transitions."""
    pass

# ------------------ WebSocket Exceptions ----------------
class WebSocketError(VoiceStaxError):
    """Raised for WebSocket-related errors."""
    pass

class WebSocketConnectionError(WebSocketError):
    """Raised when WebSocket connection fails."""
    pass
