"""ElevenLabs text-to-speech provider.

This module implements speech generation using the ElevenLabs TTS API.
It validates the configured TTS parameters and provides API key
validation and streaming speech generation through the TTS lifecycle.
"""

from typing import Any

import requests
from elevenlabs.client import ElevenLabs

from voicestax.providers.tts.base import BaseTTSProvider
from voicestax.utils.exceptions import (
    TTSConnectionError,
    TTSStreamingError,
    TTSValidationError,
)
from voicestax.utils.logger import logger


class ElevenLabsTTSProvider(BaseTTSProvider):
    """ElevenLabs-based TTS provider."""

    DEFAULTS: dict[str, Any] = {
        # ElevenLabs TTS parameters.
        "voice_id": "EXAVITQu4vr4xnSDxMaL",
        "model_id": "eleven_turbo_v2_5",
        "output_format": "pcm_24000",
        "optimize_latency": 3,
    }

    def __init__(
        self,
        api_key: str,
        log_prefix: str,
        **kwargs: Any,
    ):
        """Initialize the ElevenLabs TTS provider.

        Provider defaults can be overridden through ``**kwargs``.

        Args:
            api_key: ElevenLabs API key.
        """

        if not api_key:
            raise TTSValidationError(
                "ElevenLabs API key is required"
            )
            
        self.log_prefix = log_prefix

        # Provider defaults can be overridden by values supplied through
        # VoiceSettings.tts_config.
        self.config: dict[str, Any] = {
            **self.DEFAULTS,
            **kwargs,
        }

        self.validate_config(self.config)

        # Values required directly by VoiceStax.
        self.voice_id = self.config["voice_id"]
        self.model_id = self.config["model_id"]
        self.output_format = self.config["output_format"]
        self.optimize_latency = self.config["optimize_latency"]
        
        self.extra_config = {
                    key: value
                    for key, value in self.config.items()
                    if key not in self.DEFAULTS
                }

        # Keep the API key only for client initialization.
        self.client = ElevenLabs(api_key=api_key)

        logger.debug(
            "%s [ElevenLabs] ElevenLabs TTS provider initialized. "
            "voice_id=%s, model_id=%s, output_format=%s, "
            "optimize_latency=%s, extra_config_keys=%s",
            self.log_prefix,
            self.voice_id,
            self.model_id,
            self.output_format,
            self.optimize_latency,
            sorted(self.extra_config.keys()),
        )

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate configuration required by VoiceStax."""

        voice_id = config.get("voice_id")

        if not voice_id:
            logger.error(
                "%s [ElevenLabs] ElevenLabs voice ID is required",
                self.log_prefix,
            )
            raise TTSValidationError(
                "ElevenLabs voice_id is required"
            )

        model_id = config.get("model_id")

        if not model_id:
            logger.error(
                "%s [ElevenLabs] ElevenLabs model ID is required",
                self.log_prefix,
            )
            
            raise TTSValidationError(
                "ElevenLabs model_id is required"
            )

        output_format = config.get("output_format")

        if not output_format:
            logger.error(
                "%s [ElevenLabs] ElevenLabs output format is required",
                self.log_prefix,
            )
            raise TTSValidationError(
                "ElevenLabs output_format is required"
            )

        optimize_latency = config.get("optimize_latency")

        if (
            not isinstance(optimize_latency, int)
            or isinstance(optimize_latency, bool)
            or not 0 <= optimize_latency <= 4
        ):
            logger.error(
                "%s [ElevenLabs] Invalid ElevenLabs optimize_latency: %s",
                self.log_prefix,
                optimize_latency,
            )
            raise TTSValidationError(
                "ElevenLabs optimize_latency must be "
                "an integer between 0 and 4"
            )

    def validate_api_key(self) -> bool:
        """Validate the ElevenLabs API key."""

        try:
            logger.debug(
                "%s [ElevenLabs] Validating API key",
                self.log_prefix,
            )

            self.client.voices.get_all()

            logger.info(
                "%s [ElevenLabs] API key validation successful",
                self.log_prefix,
            )

            return True

        except requests.exceptions.ConnectionError as e:
            logger.error(
                "%s [ElevenLabs] API connection failed during validation: %s",
                self.log_prefix,
                e,
            )
            raise TTSConnectionError(
                f"Failed to connect to ElevenLabs API: {e}"
            ) from e

        except Exception as e:
            logger.error(
                "%s [ElevenLabs] API validation failed: %s",
                self.log_prefix,
                e,
            )
            raise TTSValidationError(
                f"ElevenLabs API validation failed: {e}"
            ) from e

    def stream_tts(self, text: str):
        """Generate TTS audio as a stream.

        Returns:
            Iterator of audio chunks generated by ElevenLabs.
        """

        logger.info(
            "%s [ElevenLabs] Generating speech "
            "(voice=%s, model=%s, format=%s, chars=%d)",
            self.log_prefix,
            self.voice_id,
            self.model_id,
            self.output_format,
            len(text),
        )

        try:
            params = {
                "text": text,
                "voice_id": self.voice_id,
                "model_id": self.model_id,
                "output_format": self.output_format,
                "optimize_streaming_latency": self.optimize_latency,
            }

            # Pass any additional provider-specific configuration
            # through to ElevenLabs.

            params.update(self.extra_config)

            logger.debug(
                "%s [ElevenLabs] Calling text_to_speech.convert()",
                self.log_prefix,
            )

            response = self.client.text_to_speech.convert(**params)

            logger.debug(
                "%s [ElevenLabs] text_to_speech.convert() returned response type=%s",
                self.log_prefix,
                type(response),
            )

            return response

        except requests.exceptions.ConnectionError as e:
            logger.error(
                "%s [ElevenLabs] Connection failed during TTS: %s",
                self.log_prefix,
                e,
            )
            raise TTSConnectionError(
                f"Failed to connect to ElevenLabs API during TTS: {e}"
            ) from e

        except Exception as e:
            logger.error(
                "%s [ElevenLabs] TTS streaming failed: %s",
                self.log_prefix,
                e,
            )
            raise TTSStreamingError(
                f"ElevenLabs TTS streaming failed: {e}"
            ) from e