from voicestax.session.voice_session import SessionData
class BargeInManager:

    def __init__(self, session: SessionData):
        self.session = session

    def handle_user_input(self, text: str) -> bool:
        """
        Called whenever a new transcript arrives.
        Returns True if interruption happened.
        """

        # -------- IGNORE ACCIDENTAL BARGE-IN --------
        if self.session.ignore_barge_in_once:
            self.session.ignore_barge_in_once = False
            return False

        # -------- FILTER SHORT NOISE --------
        if len(text.strip()) <= 2:
            return False

        # -------- INTERRUPT ONLY WHEN SPEAKING --------
        if self.session.is_speaking:
            self.session.trigger_barge_in()
            return True

        return False
