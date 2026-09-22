"""
Voice Agent Core Orchestration

Responsibilities:
- Orchestrates the full voice pipeline: STT -> LLM -> TTS.
- Supports true barge-in by cancelling in-flight TTS.
- Handles high-confidence local intents such as explicit goodbye.
- Uses the LLM for context-dependent intent detection.
- Delegates audio streaming to AudioManager.
- Tracks session state and conversation lifecycle.
"""

import asyncio
from fastapi import WebSocket
from voicestax.schemas.llm_schemas import LLMResponse
from voicestax.session.barge_in import BargeInManager
from voicestax.session.voice_session import SessionData
from voicestax.utils.exceptions import (
    SessionError,
    TTSError,
    WebSocketError,
)
from voicestax.utils.text_processing import detect_local_intent
from voicestax.utils.logger import logger


class VoiceAgent:
    """Orchestrates a real-time VoiceStax session."""

    DEFAULT_ERROR_RESPONSE = (
        "Sorry, I encountered an error. Please try again."
    )

    DEFAULT_GOODBYE_RESPONSE = (
        "Thank you for contacting us. Goodbye!"
    )

    DEFAULT_HANDOFF_RESPONSE = (
        "I will connect you with a human agent."
    )

    def __init__(
        self,
        session: SessionData,
        audio_manager,
        chat_engine
    ):
        self.session = session
        self.audio_manager = audio_manager
        self.chat_engine = chat_engine

        self._session_ended = False

        # The task currently streaming TTS audio.
        #
        # This task is intentionally not protected by the LLM processing lock.
        # Barge-in must be able to cancel TTS immediately.
        self._tts_task: asyncio.Task | None = None

        self.barge_manager = BargeInManager(session)

        # Validate that the session has the providers required for a voice turn.
        if not self.session.stt_provider:
                    raise SessionError(
                        "Session must have STT provider configured"
                    )
        
        if not self.session.llm_provider:
            raise SessionError(
                "Session must have LLM provider configured"
            )

        logger.debug(
            "%s [VoiceAgent] Initialized",
            self.session.log_prefix(),
        )

    @property
    def session_ended(self) -> bool:
        """Return whether the agent has requested session termination."""
        return self._session_ended

    def reset_session_ended(self) -> None:
        """Reset the terminal flag when reusing the agent/session."""
        self._session_ended = False

        logger.debug(
            "%s [VoiceAgent] Session-ended flag reset",
            self.session.log_prefix(),
        )

    async def handle_user_message(
        self,
        text: str,
        websocket: WebSocket,
    ) -> None:
        """
        Handle one final STT transcript.

        Processing order:

        1. Log the final user transcript.
        2. Handle barge-in state and cancel active TTS if required.
        3. Check high-confidence local intents.
        4. Otherwise call the LLM under the processing lock.
        5. Stream the response through TTS outside the lock.
        6. Apply terminal actions such as ending the session or handoff.
        """

        if not text or not text.strip():
            logger.debug(
                "%s [VoiceAgent] Ignoring empty user transcript",
                self.session.log_prefix(),
            )
            return

        text = text.strip()

        logger.info(
            "%s User: %s",
            self.session.log_prefix(),
            text[:100],
        )

        # ---------------------------------------------------------------
        # STEP 1: Handle barge-in before acquiring the processing lock.
        #
        # TTS cancellation must remain independent of the LLM lock.
        # Otherwise, a barge-in could wait for a slow LLM request to finish.
        # ---------------------------------------------------------------
        interrupted = self.barge_manager.handle_user_input(text)

        if interrupted:
            # Cancel the active TTS task and notify the frontend to clear audio.
            await self._cancel_tts(websocket)
        elif self.session.was_interrupted:
            logger.debug(
                "%s [VoiceAgent] Existing interruption flag detected; "
                "cancelling active TTS",
                self.session.log_prefix(),
            )
            await self._cancel_tts(websocket)
            interrupted = True

        self.session.was_interrupted = False

        if interrupted:
            logger.info(
                "%s [VoiceAgent] Barge-in handled; "
                "processing transcript as a new user turn",
                self.session.log_prefix(),
            )

        # ---------------------------------------------------------------
        # STEP 2: Handle high-confidence local intents.
        #
        # Explicit goodbye phrases and human handoff do not need an LLM call. This reduces
        # latency and avoids relying on valid JSON for session termination.
        #
        # Ambiguous phrases such as "I am done" or "that's it" are not
        # handled here; they are sent to the LLM because context matters.
        # ---------------------------------------------------------------
        local_intent = detect_local_intent(text)

        if local_intent is not None:
            logger.info(
                "%s [VoiceAgent] Local intent detected: %s",
                self.session.log_prefix(),
                local_intent,
            )
            
            # Goodbye phrases detected in user text
            if local_intent == "end_conversation":
                await self._handle_terminal_response(
                    websocket=websocket,
                    intent="end_conversation",
                    response=self.DEFAULT_GOODBYE_RESPONSE,
                )
                return

            # Human handoff phrases detected in user text
            if local_intent == "human_handoff":
                await self._handle_terminal_response(
                    websocket=websocket,
                    intent="human_handoff",
                    response=self.DEFAULT_HANDOFF_RESPONSE,
                )
                return

        # ---------------------------------------------------------------
        # STEP 3: Call the LLM.
        #
        # The processing lock protects the LLM turn only.
        # TTS is deliberately executed after releasing this lock.
        # ---------------------------------------------------------------
        intent = "conversation"
        response = self.DEFAULT_ERROR_RESPONSE
        llm_succeeded = False

        async with self.session.processing_lock:
            self.session.set_state("processing")

            # Clear cancellation from the previous turn before starting
            # a fresh LLM/TTS response.
            self.session.cancel_event.clear()

            try:
                result: LLMResponse = await asyncio.wait_for(
                    self.chat_engine.get_intent_and_response(
                        user_text=text,
                        session=self.session,
                    ),
                    timeout=self.session.settings.llm_timeout_seconds,
                )

                logger.debug(
                    "%s [VoiceAgent] LLM result received: intent=%s",
                    self.session.log_prefix(),
                    result.intent,
                )

                intent = result.intent
                response = result.response
                llm_succeeded = True

                logger.info(
                    "%s [VoiceAgent] Intent=%s",
                    self.session.log_prefix(),
                    intent,
                )

            except asyncio.TimeoutError:
                logger.error(
                    "%s [VoiceAgent] LLM request timed out after %.2f seconds",
                    self.session.log_prefix(),
                    self.session.settings.llm_timeout_seconds,
                )

            except Exception as exc:
                logger.error(
                    "%s [VoiceAgent] LLM request failed: %s: %s",
                    self.session.log_prefix(),
                    type(exc).__name__,
                    exc,
                )

        # ---------------------------------------------------------------
        # STEP 4: Do not continue with TTS if the current turn was
        # interrupted while the LLM was processing.
        # ---------------------------------------------------------------
        if self.session.cancel_event.is_set():
            logger.info(
                "%s [VoiceAgent] Skipping TTS because the turn was cancelled",
                self.session.log_prefix(),
            )
            return

        # Send the assistant text to the frontend before audio streaming.
        try:
            await websocket.send_json(
                {
                    "type": "transcript",
                    "speaker": "assistant",
                    "text": response,
                }
            )
        except Exception as exc:
            raise WebSocketError(
                f"Failed to send assistant transcript: {exc}"
            ) from exc

        if not llm_succeeded:
            logger.warning(
                "%s [VoiceAgent] Sending fallback response after LLM failure",
                self.session.log_prefix(),
            )

        # ---------------------------------------------------------------
        # STEP 5: Apply intent-specific behavior.
        # ---------------------------------------------------------------
        if intent == "end_conversation":
            await self._handle_terminal_response(
                websocket=websocket,
                intent="end_conversation",
                response=response,
                transcript_already_sent=True,
            )
            return

        if intent == "human_handoff":
            await self._handle_terminal_response(
                websocket=websocket,
                intent="human_handoff",
                response=response,
                transcript_already_sent=True,
            )
            return

        # ---------------------------------------------------------------
        # STEP 6: Normal conversational TTS.
        # ---------------------------------------------------------------
        self.session.set_state("speaking")

        logger.debug(
            "%s [VoiceAgent] Starting normal TTS response",
            self.session.log_prefix(),
        )

        await self._stream_and_track(
            websocket=websocket,
            text=response,
        )

        self.session.set_state("listening")

        logger.debug(
            "%s [VoiceAgent] Normal response completed",
            self.session.log_prefix(),
        )

    async def _handle_terminal_response(
        self,
        websocket: WebSocket,
        intent: str,
        response: str,
        transcript_already_sent: bool = False,
    ) -> None:

        # Local intents have not sent the assistant transcript yet.
        # LLM-generated terminal responses are already sent by handle_user_message(),
        # so their transcript is skipped here to avoid sending it twice.
        if not transcript_already_sent:
            try:
                await websocket.send_json(
                    {
                        "type": "transcript",
                        "speaker": "assistant",
                        "text": response,
                    }
                )
            except Exception as exc:
                raise WebSocketError(
                    f"Failed to send terminal assistant transcript: {exc}"
                ) from exc
        
        #After response is sent to frontend the state is in assistant speaking mode
        self.session.set_state("speaking")

        logger.info(
            "%s [VoiceAgent] Speaking terminal response: intent=%s",
            self.session.log_prefix(),
            intent,
        )

        await self._stream_and_track(
            websocket=websocket,
            text=response,
        )

        if intent == "end_conversation":
            try:
                await websocket.send_json(
                    {
                        "type": "session_ended",
                    }
                )
            except Exception as exc:
                raise WebSocketError(
                    f"Failed to send session-ended status: {exc}"
                ) from exc

            logger.info(
                "%s [VoiceAgent] Conversation ended",
                self.session.log_prefix(),
            )

        elif intent == "human_handoff":
            try:
                await websocket.send_json(
                    {
                        "type": "human_handoff",
                    }
                )
            except Exception as exc:
                raise WebSocketError(
                    f"Failed to send human-handoff event: {exc}"
                ) from exc

            logger.info(
                "%s [VoiceAgent] Human handoff requested",
                self.session.log_prefix(),
            )

        self._session_ended = True

    async def _stream_and_track(
        self,
        websocket: WebSocket,
        text: str,
    ) -> None:
        """
        Stream TTS through a tracked asyncio task.

        The tracked task can be cancelled immediately by _cancel_tts()
        when barge-in is detected.
        """

        tts_task = asyncio.create_task(
            self.audio_manager.stream_text(
                websocket=websocket,
                text=text,
                session=self.session,
            )
        )

        self._tts_task = tts_task

        logger.debug(
            "%s [VoiceAgent] TTS task started",
            self.session.log_prefix(),
        )

        try:
            await tts_task

        except asyncio.CancelledError:
            logger.info(
                "%s [VoiceAgent] TTS task cancelled",
                self.session.log_prefix(),
            )

        except TTSError as exc:
            logger.error(
                "%s [VoiceAgent] TTS failed: %s",
                self.session.log_prefix(),
                exc,
            )

            try:
                await websocket.send_json(
                    {
                        "type": "tts_error",
                        "message": (
                            "I'm sorry, I'm having trouble speaking "
                            "right now. Please try again."
                        ),
                        "response_id": self.session.current_response_id,
                    }
                )
            except Exception as send_exc:
                logger.warning(
                    "%s [VoiceAgent] Failed to send TTS error event: %s",
                    self.session.log_prefix(),
                    send_exc,
                )

        finally:
            # Clear only if this is still the currently tracked task.
            #
            # This prevents an older task from clearing a newer task
            # reference during a cancellation race.
            if self._tts_task is tts_task:
                self._tts_task = None

            logger.debug(
                "%s [VoiceAgent] TTS task finished",
                self.session.log_prefix(),
            )

    async def _cancel_tts(
        self,
        websocket: WebSocket,
        send_stop_audio: bool = True,
    ) -> None:
        """
        Cancel active TTS immediately during barge-in.

        Steps:
        1. Mark the session as interrupted.
        2. Cancel the currently tracked TTS task.
        3. Wait briefly for task cleanup.
        4. Ask the frontend to clear buffered audio.
        """

        logger.info(
            "%s [VoiceAgent] Barge-in detected; cancelling TTS",
            self.session.log_prefix(),
        )

        # Signal cancellation to AudioManager and any other active pipeline
        # component that checks the session interruption state.
        self.session.trigger_barge_in()

        current_tts_task = self._tts_task
        
        # Check if there is an active TTS task and if so cancel it
        if current_tts_task is not None and not current_tts_task.done():
            logger.debug(
                "%s [VoiceAgent] Cancelling active TTS task",
                self.session.log_prefix(),
            )

            current_tts_task.cancel()

            try:
                # Wait briefly for cancelled task to actually finish 
                await asyncio.wait_for(
                    asyncio.shield(current_tts_task),
                    timeout=0.5,
                )

            except asyncio.CancelledError:
                logger.debug(
                    "%s [VoiceAgent] TTS cancellation acknowledged",
                    self.session.log_prefix(),
                )

            except asyncio.TimeoutError:
                logger.warning(
                    "%s [VoiceAgent] TTS task did not finish within "
                    "cancellation timeout",
                    self.session.log_prefix(),
                )

            except Exception as exc:
                logger.warning(
                    "%s [VoiceAgent] Error while cancelling TTS task: %s",
                    self.session.log_prefix(),
                    exc,
                )

        # Verify the task instance and clear it.
        if self._tts_task is current_tts_task:
            self._tts_task = None

        # Immediately stop playback and clear browser-side audio buffers.
        if send_stop_audio:
            try:
                await websocket.send_json(
                    {
                        "type": "clear_audio",
                    }
                )

                logger.info(
                    "%s [VoiceAgent] Sent clear_audio to frontend",
                    self.session.log_prefix(),
                )

            except Exception as exc:
                logger.warning(
                    "%s [VoiceAgent] Failed to send clear_audio: %s",
                    self.session.log_prefix(),
                    exc,
                )

        logger.info(
            "%s [VoiceAgent] TTS cancellation complete",
            self.session.log_prefix(),
        )