from elevenlabs.client import ElevenLabs
from voicestax.providers.tts.base import BaseTTSProvider
from voicestax.utils.exceptions import TTSConnectionError, TTSValidationError, TTSStreamingError
import requests
from voicestax.utils.logger import logger


class ElevenLabsTTSProvider(BaseTTSProvider):
    """
    ElevenLabs TTS provider wrapper.
    """

    def __init__(
        self,
        api_key: str,
        voice_id: str = None,
        model_id: str = None,
        output_format: str = None,
        optimize_latency: bool = None
    ):
        self.client = ElevenLabs(api_key=api_key)
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format
        self.optimize_latency = optimize_latency

    def validate_api_key(self) -> bool:
        try:
            self.client.voices.get_all()
            return True
        except requests.exceptions.ConnectionError as e:
            raise TTSConnectionError(f"Failed to connect to ElevenLabs API: {e}") from e
        except Exception as e:
            # Could be authentication error or other API error
            raise TTSValidationError(f"ElevenLabs API validation failed: {e}") from e

    def stream_tts(self, text: str):
        """
        Generate TTS audio as a stream.
        """
        logger.debug("In ElevenLabsTTSProvider.stream_tts")
        logger.debug(f"text : {text}  voice_id: {self.voice_id} model_id: {self.model_id} output_format: {self.output_format} optimize_latency: {self.optimize_latency}")
        try:
            return self.client.text_to_speech.convert(
                text=text,
                voice_id=self.voice_id,
                model_id=self.model_id,
                output_format=self.output_format,
                optimize_streaming_latency=self.optimize_latency,
            )
        except requests.exceptions.ConnectionError as e:
            raise TTSConnectionError(f"Failed to connect to ElevenLabs API during TTS: {e}") from e
        except Exception as e:
            raise TTSStreamingError(f"ElevenLabs TTS streaming failed: {e}") from e