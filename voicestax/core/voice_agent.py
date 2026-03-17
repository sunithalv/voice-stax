"""
Voice Agent Core Orchestration

- Handles full voice pipeline: STT → LLM → TTS
- Supports true barge-in: cancels in-flight TTS task immediately
- Uses LLM intent detection
- Delegates audio streaming to AudioManager
- Tracks session state and conversation
"""

import asyncio
import json
import re

from fastapi import WebSocket
from voicestax.utils.logger import logger
from voicestax.schemas.llm_schemas import LLMResponse
from voicestax.session.voice_session import SessionData
from voicestax.session.barge_in import BargeInManager
from voicestax.config.settings import VoiceSettings, get_settings
from typing import Optional
from voicestax.utils.exceptions import SessionError, WebSocketError


class VoiceAgent:
    """Orchestrates a real-time voice session."""

    def __init__(self, session: SessionData, audio_manager, chat_engine,settings: Optional[VoiceSettings] = None):
        self.settings = get_settings(override=settings)
        self.session = session
        self.audio_manager = audio_manager
        self.chat_engine = chat_engine
        self.barge_manager = BargeInManager(session)

        # Validate session has required providers
        if not self.session.llm_provider:
            raise SessionError("Session must have LLM provider configured")
        if not self.session.stt_provider:
            raise SessionError("Session must have STT provider configured")

        # Track the currently running TTS asyncio Task so we can cancel it
        # the instant a barge-in is detected — before acquiring any lock.
        self._tts_task: asyncio.Task | None = None

    # ─────────────────────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────────────────────

    async def handle_user_message(self, text: str, websocket: WebSocket):
        """
        Called for every final STT transcript.

        Steps:
          1. Immediately cancel any in-flight TTS (barge-in).
          2. Acquire processing lock ONLY for the LLM call (not TTS).
          3. Release lock, then stream TTS as a tracked Task.
             This way the next barge-in can acquire the lock immediately.
        """

        # ── STEP 1: Barge-in — cancel TTS BEFORE acquiring the lock ──────────
        interrupted = self.barge_manager.handle_user_input(text)
        # Also cancel if VAD already fired but BargeInManager missed it
        if not interrupted and self.session.was_interrupted:
            await self._cancel_tts(websocket)
            interrupted = True
        
        self.session.was_interrupted = False  # reset after handling
        # ── STEP 2 & 3: Lock covers ONLY the LLM call ────────────────────────
        # TTS is intentionally outside the lock so _cancel_tts can be called
        # by a concurrent interrupt without deadlocking.
        intent   = "continue"
        response = "Sorry, I encountered an error."

        async with self.session.processing_lock:
            self.session.set_state("processing")
            # Clear cancel so this fresh response streams without being
            # immediately aborted by a stale cancel_event from the previous turn.
            self.session.cancel_event.clear()

            try:
                raw_result = await self.chat_engine.get_intent_and_response(
                    user_text=text,
                    session=self.session,
                )
                logger.debug(f"💬 LLM raw result: {raw_result}")

                if isinstance(raw_result, str):
                    match = re.search(r'\{.*\}', raw_result, re.DOTALL)
                    raw_result = json.loads(match.group()) if match else {}

                validated = LLMResponse(**raw_result)
                intent    = validated.intent
                response  = validated.response

            except Exception as e:
                logger.error(f"[LLM ERROR]: {e}")
                # intent/response already set to safe defaults above

        # ── STEP 4: TTS — runs OUTSIDE the lock ──────────────────────────────
        self.session.ignore_barge_in_once = False

        if intent == "end_session":
            self.session.set_state("speaking")
            await self._stream_and_track(websocket, response)
            try:
                await websocket.send_json({"type": "status", "text": "Session ended"})
            except Exception as e:
                raise WebSocketError(f"Failed to send session ended status: {e}") from e
            if self.session.stt_provider:
                self.session.stt_provider.stop_streaming()
            self.session.set_state("idle")
            self.session.reset_session()
            return

        self.session.set_state("speaking")
        await self._stream_and_track(websocket, response)

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    async def _stream_and_track(self, websocket: WebSocket, text: str):
        """
        Run stream_text as a tracked asyncio Task stored in self._tts_task.
        The lock is held only for LLM; TTS runs outside it so barge-in can
        cancel without deadlocking.
        """
        self._tts_task = asyncio.create_task(
            self.audio_manager.stream_text(
                websocket=websocket,
                text=text,
                session=self.session,
            )
        )
        try:
            await self._tts_task
        except asyncio.CancelledError:
            pass  # barge-in cancelled it — that's expected
        finally:
            self._tts_task = None

    async def _cancel_tts(self, websocket: WebSocket, send_stop_audio=True):
        """
        Immediately stop any in-flight TTS:
          1. Set the session cancel flag (stops chunk loop in AudioManager).
          2. Cancel the asyncio Task (unblocks any awaiting sleep/queue).
          3. Tell the frontend to stop audio playback right now.
        """
        self.session.was_interrupted = True
        self.session.is_speaking = False
        self.session.cancel_event.set()

        if self._tts_task and not self._tts_task.done():
            self._tts_task.cancel()
            try:
                await asyncio.wait_for(self._tts_task, timeout=0.5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        self._tts_task = None

        # Tell the frontend: stop audio, discard buffers, reset UI
        if send_stop_audio:                          # ← conditional
            try:
                await websocket.send_json({"type": "stop_audio"})
            except Exception as e:
                raise WebSocketError(f"Failed to send stop_audio message: {e}") from e
        logger.info("[BARGE-IN] TTS cancelled, stop_audio sent to frontend")