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
        speech_confirmation_frames: int = 3,
    ) -> None:

        """Initialize the VAD session state manager.

        Args:
            silence_threshold_ms: Amount of continuous silence required
                to consider an utterance complete.
            frame_duration_ms: Duration represented by each VAD frame.
            max_utterance_ms: Maximum allowed utterance duration.
            speech_confirmation_frames: Number of consecutive speech
                frames required before speech is considered confirmed.
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

        if (
            not isinstance(speech_confirmation_frames, int)
            or isinstance(speech_confirmation_frames, bool)
            or speech_confirmation_frames <= 0
        ):
            raise ValueError(
                "speech_confirmation_frames must be a positive integer"
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
        self.speech_confirmation_frames = speech_confirmation_frames

        self.in_speech = False
        self.silence_ms = 0
        self.speech_frames = 0
        self.speech_candidate_frames = 0

        logger.info(
            "Initialized VADManager "
            "(frame_duration=%dms, silence_threshold=%dms, "
            "max_utterance=%dms, speech_confirmation_frames=%d)",
            frame_duration_ms,
            silence_threshold_ms,
            max_utterance_ms,
            speech_confirmation_frames,
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

            # Speech has not yet been confirmed.
            if not self.in_speech:
                self.speech_candidate_frames += 1

                if (
                    self.speech_candidate_frames
                    < self.speech_confirmation_frames
                ):
                    return events

                # Speech is now confirmed.
                self.in_speech = True
                self.speech_frames = 0
                self.silence_ms = 0

                events.append("speech_started")

                logger.info(
                    "VAD: speech started "
                    "(confirmed after %d frames)",
                    self.speech_candidate_frames,
                )

            self.speech_frames += 1
            self.silence_ms = 0

            if self.speech_frames >= self.max_utterance_frames:
                logger.warning("VAD: max segment duration reached")
                # Reset only the current segment counter.
                # Preserve the active speech state.
                self.speech_frames = 0
                self.silence_ms = 0
                events.append("max_utterance")

        else:

            # Silence before speech has been confirmed.
            if not self.in_speech:
                self.speech_candidate_frames = 0
                return events

            # Silence during a confirmed utterance.
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
        self.speech_candidate_frames = 0