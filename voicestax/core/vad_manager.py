"""VoiceStax voice activity detection session manager.

This module coordinates provider-level voice activity detection with
VoiceStax utterance-level state management. It tracks speech onset,
silence duration, and maximum utterance duration.
"""

from voicestax.utils.logger import logger


class VADManager:
    """Manage speech state and utterance boundaries for a session."""

    def __init__(
        self,
        silence_threshold_ms: int,
        frame_duration_ms: int,
        max_utterance_ms: int,
    ) -> None:
        
        """Initialize the VAD session state manager.

        Args:
            silence_threshold_ms: Amount of continuous silence required
                to consider an utterance complete.
            frame_duration_ms: Duration represented by each VAD frame.
            max_utterance_ms: Maximum allowed utterance duration.
        """

        if frame_duration_ms <= 0:
            raise ValueError(
                "frame_duration_ms must be positive"
            )

        if (
            not isinstance(silence_threshold_ms, int)
            or isinstance(silence_threshold_ms, bool)
            or silence_threshold_ms <= 0
        ):
            raise ValueError(
                "silence_threshold_ms must be a positive integer"
            )

        if (
            not isinstance(max_utterance_ms, int)
            or isinstance(max_utterance_ms, bool)
            or max_utterance_ms <= 0
        ):
            raise ValueError(
                "max_utterance_ms must be a positive integer"
            )

        max_utterance_frames = (
            max_utterance_ms // frame_duration_ms
        )

        if max_utterance_frames <= 0:
            raise ValueError(
                "max_utterance_ms must be at least "
                "frame_duration_ms"
            )

        self.frame_duration_ms = frame_duration_ms
        self.silence_threshold_ms = silence_threshold_ms
        self.max_utterance_frames = max_utterance_frames

        self.in_speech = False
        self.silence_ms = 0
        self.speech_frames = 0

        logger.info(
            "Initialized VADManager "
            "(frame_duration=%dms, silence_threshold=%dms, "
            "max_utterance=%dms)",
            frame_duration_ms,
            silence_threshold_ms,
            max_utterance_ms,
        )

    def process_frame(self, is_speech: bool) -> list[str]:
        """Process one VAD frame and return any state-change events.

        Args:
            is_speech: Whether the VAD provider classified the
                current frame as speech.

        Returns:
            A list containing zero or more event labels:

            - ``speech_started``
            - ``speech_ended``
            - ``max_utterance``
        """

        events: list[str] = []

        if is_speech:
            if not self.in_speech:
                self.in_speech = True
                self.speech_frames = 0
                events.append("speech_started")

                logger.info("VAD: speech started")

            self.speech_frames += 1
            self.silence_ms = 0

            if self.speech_frames >= self.max_utterance_frames:
                logger.warning("VAD: max utterance reached")

                self.reset()
                events.append("max_utterance")

        else:
            if self.in_speech:
                self.silence_ms += self.frame_duration_ms

                if self.silence_ms >= self.silence_threshold_ms:
                    speech_frames = self.speech_frames

                    logger.info(
                        "VAD: speech ended "
                        "(speech_frames=%d)",
                        speech_frames,
                    )

                    self.reset()
                    events.append("speech_ended")

        return events

    def reset(self) -> None:
        """Reset the VAD state machine to its initial state."""

        self.in_speech = False
        self.silence_ms = 0
        self.speech_frames = 0