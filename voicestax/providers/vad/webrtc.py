"""WebRTC Voice Activity Detection provider.

This module implements speech detection using the WebRTC VAD engine.
It validates the configured WebRTC VAD parameters and incoming PCM
frame sizes before delegating speech classification to WebRTC VAD.
"""

from typing import Any

import webrtcvad

from voicestax.providers.vad.base import BaseVAD
from voicestax.utils.logger import logger


class WebRTCVAD(BaseVAD):
    """WebRTC-based VAD provider."""

    # WebRTC VAD accepts only these PCM sample rates.
    SUPPORTED_SAMPLE_RATES = {
        8000,
        16000,
        32000,
        48000,
    }

    # WebRTC VAD accepts only 10 ms, 20 ms, or 30 ms frames.
    VALID_DURATIONS_MS = (
        10,
        20,
        30,
    )

    DEFAULTS: dict[str, Any] = {
        "aggressiveness": 2,
        "sample_rate": 16000,
        "frame_duration_ms": 20,
    }

    def __init__(self, **kwargs: Any):
        """Initialize the WebRTC VAD provider.

        Provider defaults can be overridden through ``**kwargs``.
        Unsupported configuration parameters raise ``ValueError``.
        """

        # Reject unsupported configuration parameters instead of
        # silently accepting and storing unused values.
        unsupported_keys = set(kwargs) - set(self.DEFAULTS)

        if unsupported_keys:
            logger.error(
                "Unsupported WebRTC VAD configuration: %s",
                sorted(unsupported_keys),
            )
            raise ValueError(
                "Unsupported WebRTC VAD configuration: "
                f"{sorted(unsupported_keys)}"
            )

        # Merge provider defaults with user-supplied configuration.
        # User values override the defaults.
        self.config: dict[str, Any] = {
            **self.DEFAULTS,
            **kwargs,
        }

        self.validate_config(self.config)

        self.aggressiveness = self.config["aggressiveness"]
        self.sample_rate = self.config["sample_rate"]
        self.frame_duration_ms = self.config["frame_duration_ms"]

        # Initialize the WebRTC VAD engine.
        # WebRTC itself uses the aggressiveness setting when
        # creating the VAD instance.
        self.vad = webrtcvad.Vad(self.aggressiveness)

        # WebRTC VAD requires PCM 16-bit mono frames with a duration
        # of exactly 10, 20, or 30 ms.
        #
        # Each PCM 16-bit sample uses 2 bytes, so calculate the
        # expected frame size for the configured duration.
        frame_size = (
            int(
                self.sample_rate
                * self.frame_duration_ms
                / 1000
            )
            * 2
        )

        self.valid_frame_sizes = {frame_size}

        logger.debug(
            "WebRTC VAD provider initialized. "
            "aggressiveness=%s, sample_rate=%s, "
            "frame_duration_ms=%s",
            self.aggressiveness,
            self.sample_rate,
            self.frame_duration_ms,
        )

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate WebRTC VAD configuration."""

        aggressiveness = config.get("aggressiveness")

        if (
            not isinstance(aggressiveness, int)
            or isinstance(aggressiveness, bool)
            or aggressiveness not in (0, 1, 2, 3)
        ):
            logger.error(
                "Invalid WebRTC VAD aggressiveness: %s",
                aggressiveness,
            )
            raise ValueError(
                f"Invalid VAD aggressiveness: {aggressiveness}"
            )

        sample_rate = config.get("sample_rate")

        if sample_rate not in self.SUPPORTED_SAMPLE_RATES:
            logger.error(
                "Unsupported WebRTC VAD sample rate: %s",
                sample_rate,
            )
            raise ValueError(
                f"Unsupported sample rate: {sample_rate}"
            )

        frame_duration_ms = config.get("frame_duration_ms")

        if frame_duration_ms not in self.VALID_DURATIONS_MS:
            logger.error(
                "Unsupported WebRTC VAD frame duration: %s ms",
                frame_duration_ms,
            )
            raise ValueError(
                "WebRTC VAD frame duration must be 10, 20, or 30 ms"
            )

    def is_speech(
        self,
        audio_chunk: bytes,
    ) -> bool:
        """Return True if the audio frame contains speech.

        The incoming chunk must be a valid PCM 16-bit mono frame
        matching the configured frame duration.
        """

        # WebRTC VAD only accepts frames corresponding to
        # 10, 20, or 30 ms of audio at the configured sample rate.
        if len(audio_chunk) not in self.valid_frame_sizes:
            logger.warning(
                "Invalid WebRTC VAD frame size: %d bytes "
                "(expected %s)",
                len(audio_chunk),
                sorted(self.valid_frame_sizes),
            )
            raise ValueError(
                f"Invalid frame size: {len(audio_chunk)}"
            )

        return self.vad.is_speech(
            audio_chunk,
            self.sample_rate,
        )
