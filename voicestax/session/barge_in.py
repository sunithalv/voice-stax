from voicestax.session.voice_session import SessionData
from voicestax.utils.logger import logger


class BargeInManager:
    """Detect barge-in requests during assistant speech."""

    def __init__(self, session: SessionData):
        self.session = session

    def handle_user_input(self, text: str) -> bool:
        """
        Detect whether an incoming transcript interrupts assistant speech.

        Returns:
            True if the transcript arrived while the assistant was speaking.
        """

        # Prevent the assistant's own voice or echo from causing an interruption.
        if self.session.ignore_barge_in_once:
            logger.debug(
                "%s Ignoring one transcript after TTS completion",
                self.session.log_prefix(),
            )
            self.session.ignore_barge_in_once = False
            return False

        # Ignore very short transcripts likely to be noise.
        if len(text.strip()) <= 2:
            logger.debug(
                "%s Ignoring short transcript: '%s'",
                self.session.log_prefix(),
                text,
            )
            return False

        # Detect interruption only while the assistant is speaking.
        if self.session.is_speaking:
            logger.info(
                "%s Barge-in detected: '%s'",
                self.session.log_prefix(),
                text,
            )
            return True

        logger.debug(
            "%s No barge-in detected",
            self.session.log_prefix(),
        )
        return False