"""
AssemblyAI speech-to-text provider for streaming microphone audio.

Responsibilities:
- Connect to AssemblyAI's v3 streaming WebSocket.
- Send raw PCM audio.
- Receive partial and final transcripts.
- Support microphone mute/unmute while TTS is playing.
- Support forced turn completion.
- Pass provider-specific configuration through to AssemblyAI.
- Keep VoiceStax-internal configuration separate from AssemblyAI parameters.
"""

import asyncio
import json
from typing import Any, Callable, Optional
from urllib.parse import urlencode

import websockets

from voicestax.providers.stt.base import BaseSTTProvider
from voicestax.utils import session
from voicestax.utils.exceptions import (
    STTConnectionError,
    STTError,
    STTStreamingError,
)
from voicestax.utils.logger import logger


TranscriptCallback = Callable[[str, bool], None]
ErrorCallback = Callable[[Exception], None]


class AssemblyAISTTProvider(BaseSTTProvider):
    """
    AssemblyAI streaming STT provider.

    Provider-specific parameters are accepted through **kwargs and passed
    to AssemblyAI as WebSocket query parameters.

    Example:

        AssemblyAISTTProvider(
            api_key="...",
            sample_rate=16000,
            encoding="pcm_s16le",
            speech_model="u3-rt-pro",
            format_turns=True,
            min_turn_silence=400,
            max_turn_silence=1500,
            keyterms_prompt=[
                "VoiceStax",
                "AssemblyAI",
                "customer support",
            ],
        )

    VoiceStax-internal settings are not sent to AssemblyAI. At present,
    formatted_transcript_wait_ms is handled internally by VoiceStax.
    """

    ASSEMBLYAI_WS_URL = "wss://streaming.assemblyai.com/v3/ws"

    DEFAULTS: dict[str, Any] = {
        # AssemblyAI connection parameters.
        "sample_rate": 16000,
        "encoding": "pcm_s16le",
        "format_turns": True,
        "end_of_turn_confidence_threshold": 0.6,
        "min_end_of_turn_silence_when_confident": 300,

        # VoiceStax-internal parameter.
        # This controls how long VoiceStax waits for a formatted turn
        # before emitting the unformatted final transcript.
        "formatted_transcript_wait_ms": 350,
    }

    # These values are consumed by VoiceStax and must not be included
    # in the AssemblyAI WebSocket query string.
    INTERNAL_CONFIG_KEYS = {
        "formatted_transcript_wait_ms",
    }

    def __init__(self, api_key: str, **kwargs: Any):
        """
        Initialize the AssemblyAI provider.

        Unknown kwargs are intentionally accepted. This allows users to
        supply newly introduced AssemblyAI parameters without requiring
        a VoiceStax source-code update.
        """

        if not api_key:
            raise STTConnectionError(
                "AssemblyAI API key is required"
            )

        self.api_key = api_key

        # Provider defaults can be overridden by values supplied through
        # VoiceSettings.stt_config.
        self.config: dict[str, Any] = {
            **self.DEFAULTS,
            **kwargs,
        }

        self.validate_config(self.config)

        # Values required directly by VoiceStax.
        self.sample_rate = self.config["sample_rate"]
        self.encoding = self.config["encoding"]

        self.end_of_turn_confidence_threshold = self.config[
            "end_of_turn_confidence_threshold"
        ]

        self.min_end_of_turn_silence_when_confident = self.config[
            "min_end_of_turn_silence_when_confident"
        ]

        self.formatted_transcript_wait_ms = self.config[
            "formatted_transcript_wait_ms"
        ]

        # High-level provider state.
        self._is_listening = False
        self.is_streaming = False
        self._muted = False

        # Transcript state.
        self._last_partial = ""
        self._pending_unformatted = ""
        self._pending_unformatted_task: Optional[asyncio.Task] = None

        # WebSocket and task state.
        self._ws = None
        self._stream_task: Optional[asyncio.Task] = None
        self._cancel_event = asyncio.Event()
        self._send_lock = asyncio.Lock()

        logger.debug(
            "%s [AssemblyAI] Connection configuration keys: %s",
            session.get_log_prefix(),
            sorted(
                key
                for key in self.config
                if key not in self.INTERNAL_CONFIG_KEYS
            ),
        )

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate configuration values required by VoiceStax."""

        sample_rate = config.get("sample_rate")

        if (
            not isinstance(sample_rate, int)
            or isinstance(sample_rate, bool)
            or sample_rate <= 0
        ):
            raise ValueError(
                "AssemblyAI sample_rate must be a positive integer"
            )

        encoding = config.get("encoding")

        if not isinstance(encoding, str) or not encoding.strip():
            raise ValueError(
                "AssemblyAI encoding must be a non-empty string"
            )

        confidence = config.get(
            "end_of_turn_confidence_threshold"
        )

        if not isinstance(confidence, (int, float)):
            raise ValueError(
                "AssemblyAI "
                "end_of_turn_confidence_threshold must be numeric"
            )

        if not 0 <= confidence <= 1:
            raise ValueError(
                "AssemblyAI "
                "end_of_turn_confidence_threshold must be between 0 and 1"
            )

        silence_ms = config.get(
            "min_end_of_turn_silence_when_confident"
        )

        if (
           not isinstance(silence_ms, int) 
           or isinstance(silence_ms, bool) 
           or silence_ms < 0
        ):
            raise ValueError(
                "AssemblyAI "
                "min_end_of_turn_silence_when_confident must be "
                "a non-negative integer"
            )

        formatted_wait_ms = config.get(
            "formatted_transcript_wait_ms"
        )

        if (
            not isinstance(formatted_wait_ms, int)
            or isinstance(formatted_wait_ms, bool)
            or formatted_wait_ms < 0
        ):
            raise ValueError(
                "formatted_transcript_wait_ms must be "
                "a non-negative integer"
            )

    @property
    def is_ready(self) -> bool:
        """Return True when the AssemblyAI WebSocket is connected."""
        return self.is_streaming

    def validate_api_key(self) -> bool:
        """
        Validate that an API key was supplied.

        This checks local configuration only. Actual authentication is
        ultimately validated by AssemblyAI when the WebSocket connects.
        """
        return bool(self.api_key)

    def is_listening(self) -> bool:
        """Return whether the provider is currently listening."""
        return self._is_listening

    def mute(self) -> None:
        """
        Mute microphone audio while TTS is playing.

        The WebSocket remains connected, but audio chunks are ignored
        until unmute() is called.
        """
        self._muted = True
        self._last_partial = ""

        logger.debug(
            "%s [AssemblyAI] Microphone muted",
            session.get_log_prefix(),
        )

    def unmute(self) -> None:
        """Resume microphone audio after TTS finishes."""
        self._muted = False

        logger.debug(
            "%s [AssemblyAI] Microphone unmuted",
            session.get_log_prefix(),
        )

    async def send_audio(self, audio_chunk: bytes) -> None:
        """
        Send raw PCM audio bytes to AssemblyAI.

        Audio is ignored when:
        - streaming has not started,
        - the WebSocket is unavailable,
        - listening has stopped, or
        - the provider is muted.
        """

        if (
            not self.is_streaming
            or self._ws is None
            or not self._is_listening
        ):
            logger.debug(
                "%s [AssemblyAI] Ignoring audio; "
                "provider is not actively streaming",
                session.get_log_prefix(),
            )
            return

        if self._muted:
            logger.debug(
                "%s [AssemblyAI] Ignoring audio; provider is muted",
                session.get_log_prefix(),
            )
            return

        if not isinstance(audio_chunk, bytes):
            raise STTStreamingError(
                "AssemblyAI audio_chunk must be bytes"
            )

        async with self._send_lock:
            try:
                # AssemblyAI v3 accepts raw binary audio frames.
                await self._ws.send(audio_chunk)

            except websockets.exceptions.ConnectionClosed as exc:
                self.is_streaming = False
                self._is_listening = False

                logger.error(
                    "%s [AssemblyAI] WebSocket closed while "
                    "sending audio: %s",
                    session.get_log_prefix(),
                    exc,
                )

                raise STTConnectionError(
                    f"AssemblyAI WebSocket closed: {exc}"
                ) from exc

            except Exception as exc:
                logger.exception(
                    "%s [AssemblyAI] Audio send failed",
                    session.get_log_prefix(),
                )

                raise STTStreamingError(
                    f"Failed to send audio to AssemblyAI: {exc}"
                ) from exc

    def start_streaming(
        self,
        on_transcript: TranscriptCallback,
        on_error: ErrorCallback,
    ) -> None:
        """
        Start the AssemblyAI streaming task.

        The method is intentionally non-async so the caller can start
        streaming without blocking its WebSocket or audio loop.
        """

        if self._is_listening:
            logger.debug(
                "%s [AssemblyAI] start_streaming ignored; "
                "provider is already listening",
                session.get_log_prefix(),
            )
            return

        self._is_listening = True
        self.is_streaming = False
        self._cancel_event.clear()

        self._last_partial = ""
        self._pending_unformatted = ""

        if (
            self._pending_unformatted_task
            and not self._pending_unformatted_task.done()
        ):
            self._pending_unformatted_task.cancel()

        self._pending_unformatted_task = None

        self._stream_task = asyncio.create_task(
            self._run_stream(
                on_transcript=on_transcript,
                on_error=on_error,
            )
        )

        logger.info(
            "%s [AssemblyAI] Streaming task started",
            session.get_log_prefix(),
        )

    def stop_streaming(self) -> None:
        """
        Request that the streaming task stop.

        The receive loop is responsible for sending the termination
        message and cleaning up the WebSocket.
        """

        if not self._is_listening and not self.is_streaming:
            logger.debug(
                "%s [AssemblyAI] stop_streaming ignored; "
                "provider is already stopped",
                session.get_log_prefix(),
            )
            return

        self._is_listening = False
        self.is_streaming = False
        self._cancel_event.set()

        logger.info(
            "%s [AssemblyAI] Streaming stop requested",
            session.get_log_prefix(),
        )

    def _build_stream_url(self) -> str:
        """
        Build the AssemblyAI WebSocket URL.

        All configuration values are passed through except values that
        are explicitly owned by VoiceStax.

        urlencode(..., doseq=True) supports list-valued parameters such
        as keyterms_prompt.
        """

        connection_params = {
            key: value
            for key, value in self.config.items()
            if key not in self.INTERNAL_CONFIG_KEYS
            and value is not None
        }

        query_string = urlencode(
            connection_params,
            doseq=True,
        )

        return f"{self.ASSEMBLYAI_WS_URL}?{query_string}"


    async def _run_stream(
        self,
        on_transcript: TranscriptCallback,
        on_error: ErrorCallback,
    ) -> None:
        """Maintain the AssemblyAI WebSocket connection and receive loop."""

        url = self._build_stream_url()

        headers = {
            "Authorization": self.api_key,
        }

        logger.info(
            "%s [AssemblyAI] Connecting to streaming service",
            session.get_log_prefix(),
        )

        logger.debug(
            "%s [AssemblyAI] Connection configuration keys: %s",
            session.get_log_prefix(),
            sorted(
                key
                for key in self.config
                if key not in self.INTERNAL_CONFIG_KEYS
            ),
        )

        try:
            async with websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=10,
                ping_timeout=20,
            ) as websocket:
                self._ws = websocket
                self.is_streaming = True

                logger.info(
                    "%s [AssemblyAI] WebSocket connected",
                    session.get_log_prefix(),
                )

                while self._is_listening:
                    cancel_task = asyncio.create_task(
                        self._cancel_event.wait()
                    )

                    receive_task = asyncio.create_task(
                        websocket.recv()
                    )

                    done, pending = await asyncio.wait(
                        [receive_task, cancel_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    for task in pending:
                        task.cancel()

                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                    if cancel_task in done:
                        logger.info(
                            "%s [AssemblyAI] Cancellation received",
                            session.get_log_prefix(),
                        )

                        await self._terminate_session(websocket)
                        break

                    if receive_task not in done:
                        continue

                    try:
                        message = receive_task.result()

                    except websockets.exceptions.ConnectionClosed as exc:
                        logger.error(
                            "%s [AssemblyAI] WebSocket closed while "
                            "receiving: %s",
                            session.get_log_prefix(),
                            exc,
                        )

                        on_error(
                            STTConnectionError(
                                f"AssemblyAI connection closed: {exc}"
                            )
                        )
                        break

                    except Exception as exc:
                        logger.exception(
                            "%s [AssemblyAI] Receive failed",
                            session.get_log_prefix(),
                        )

                        on_error(
                            STTStreamingError(
                                f"AssemblyAI receive failed: {exc}"
                            )
                        )
                        break

                    data = self._parse_message(message)

                    if data is None:
                        continue

                    await self._handle_message(
                        data=data,
                        on_transcript=on_transcript,
                        on_error=on_error,
                    )

        except Exception as exc:
            logger.exception(
                "%s [AssemblyAI] Streaming connection failed",
                session.get_log_prefix(),
            )

            # Avoid reporting a second error if the receive loop already
            # delivered an error callback and the provider was stopped.
            if self._is_listening:
                on_error(
                    STTStreamingError(
                        "AssemblyAI streaming failed. "
                        "Check your stt_config parameters and API key. "
                        f"Details: {exc}"
                    )
                )

        finally:
            self._is_listening = False
            self.is_streaming = False
            self._ws = None

            if (
                self._pending_unformatted_task
                and not self._pending_unformatted_task.done()
            ):
                self._pending_unformatted_task.cancel()

            self._pending_unformatted_task = None
            self._pending_unformatted = ""

            logger.info(
                "%s [AssemblyAI] WebSocket closed and provider reset",
                session.get_log_prefix(),
            )

    async def _terminate_session(self, websocket) -> None:
        """Ask AssemblyAI to terminate the current streaming session."""

        try:
            await websocket.send(
                json.dumps(
                    {
                        "terminate_session": True,
                    }
                )
            )

            logger.debug(
                "%s [AssemblyAI] Termination message sent",
                session.get_log_prefix(),
            )

        except Exception as exc:
            # Termination can fail if the server has already closed the
            # connection. Cleanup still continues in the caller.
            logger.debug(
                "%s [AssemblyAI] Could not send termination message: %s",
                session.get_log_prefix(),
                exc,
            )

    def _parse_message(
        self,
        message: Any,
    ) -> Optional[dict[str, Any]]:
        """Parse an AssemblyAI WebSocket message into a dictionary."""

        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8")
            except UnicodeDecodeError:
                logger.warning(
                    "%s [AssemblyAI] Ignoring non-UTF-8 message",
                    session.get_log_prefix(),
                )
                return None

        if not isinstance(message, str):
            logger.warning(
                "%s [AssemblyAI] Ignoring unexpected message type: %s",
                session.get_log_prefix(),
                type(message).__name__,
            )
            return None

        try:
            data = json.loads(message)

        except json.JSONDecodeError:
            logger.warning(
                "%s [AssemblyAI] Ignoring invalid JSON message: %s",
                session.get_log_prefix(),
                message[:200],
            )
            return None

        if not isinstance(data, dict):
            logger.warning(
                "%s [AssemblyAI] Ignoring non-object message: %s",
                session.get_log_prefix(),
                type(data).__name__,
            )
            return None

        logger.debug(
            "%s [AssemblyAI] Received message type=%s",
            session.get_log_prefix(),
            data.get("type"),
        )

        return data

    async def _handle_message(
        self,
        data: dict[str, Any],
        on_transcript: TranscriptCallback,
        on_error: ErrorCallback,
    ) -> None:
        """Handle one parsed AssemblyAI server message."""

        message_type = data.get("type", "")

        if message_type == "Begin":
            logger.info(
                "%s [AssemblyAI] Session began: id=%s",
                session.get_log_prefix(),
                data.get("id"),
            )
            return

        if message_type == "PartialTranscript":
            text = data.get("text", "").strip()

            if text:
                self._last_partial = text

                logger.debug(
                    "%s [AssemblyAI] Partial transcript: %s",
                    session.get_log_prefix(),
                    text,
                )

                on_transcript(text, False)

            return

        if message_type == "Turn":
            await self._handle_turn(
                data=data,
                on_transcript=on_transcript,
            )
            return

        if message_type == "Termination":
            logger.info(
                "%s [AssemblyAI] Server terminated session: %s",
                session.get_log_prefix(),
                data,
            )

            self._is_listening = False
            return

        if message_type.lower() == "error" or "error" in data:
            error_message = data.get(
                "error",
                str(data),
            )

            logger.error(
                "%s [AssemblyAI] Provider error: %s",
                session.get_log_prefix(),
                error_message,
            )

            on_error(STTError(str(error_message)))
            self._is_listening = False
            return

        logger.debug(
            "%s [AssemblyAI] Unhandled message type: %s",
            session.get_log_prefix(),
            message_type,
        )

    async def _handle_turn(
        self,
        data: dict[str, Any],
        on_transcript: TranscriptCallback,
    ) -> None:
        """Handle a final or non-final AssemblyAI Turn message."""

        is_final = data.get("end_of_turn", False)

        if not is_final:
            return

        transcript = data.get("transcript", "").strip()

        if not transcript:
            logger.debug(
                "%s [AssemblyAI] Final Turn contained no transcript",
                session.get_log_prefix(),
            )
            return

        turn_is_formatted = data.get(
            "turn_is_formatted",
            False,
        )

        if turn_is_formatted:
            await self._handle_formatted_turn(
                transcript=transcript,
                on_transcript=on_transcript,
            )
        else:
            await self._handle_unformatted_turn(
                transcript=transcript,
                on_transcript=on_transcript,
            )

    async def _handle_formatted_turn(
        self,
        transcript: str,
        on_transcript: TranscriptCallback,
    ) -> None:
        """Emit a formatted final transcript immediately."""

        if (
            self._pending_unformatted_task
            and not self._pending_unformatted_task.done()
        ):
            self._pending_unformatted_task.cancel()
            self._pending_unformatted_task = None

            logger.debug(
                "%s [AssemblyAI] Cancelled pending unformatted "
                "transcript because formatted transcript arrived",
                session.get_log_prefix(),
            )

        self._pending_unformatted = ""
        self._last_partial = ""

        logger.info(
            "%s [AssemblyAI] Final formatted transcript: %s",
            session.get_log_prefix(),
            transcript,
        )

        on_transcript(transcript, True)

    async def _handle_unformatted_turn(
        self,
        transcript: str,
        on_transcript: TranscriptCallback,
    ) -> None:
        """
        Temporarily hold an unformatted final transcript.

        AssemblyAI may send a formatted version shortly afterwards.
        VoiceStax waits before emitting the unformatted version.
        """

        self._pending_unformatted = transcript

        if (
            self._pending_unformatted_task
            and not self._pending_unformatted_task.done()
        ):
            self._pending_unformatted_task.cancel()

        self._pending_unformatted_task = asyncio.create_task(
            self._emit_if_no_formatted(
                transcript=transcript,
                on_transcript=on_transcript,
            )
        )

        logger.debug(
            "%s [AssemblyAI] Holding unformatted final transcript "
            "for %sms: %s",
            session.get_log_prefix(),
            self.formatted_transcript_wait_ms,
            transcript,
        )

    async def force_end_turn(
        self,
        fallback_callback: Optional[TranscriptCallback] = None,
    ) -> None:
        """
        Force AssemblyAI to finalize the current speech turn.

        If AssemblyAI does not return a final transcript quickly enough,
        the latest partial transcript can optionally be emitted through
        fallback_callback.
        """

        if self._ws is None or not self.is_streaming:
            logger.debug(
                "%s [AssemblyAI] force_end_turn ignored; "
                "WebSocket is not active",
                session.get_log_prefix(),
            )
            return

        try:
            await self._ws.send(
                json.dumps(
                    {
                        "type": "ForceEndpoint",
                    }
                )
            )

            logger.info(
                "%s [AssemblyAI] ForceEndpoint sent",
                session.get_log_prefix(),
            )

            partial_at_interrupt = self._last_partial

            # Give AssemblyAI time to return the final turn.
            await asyncio.sleep(
                self.min_end_of_turn_silence_when_confident / 1000
            )

            if (
                partial_at_interrupt
                and self._last_partial == partial_at_interrupt
                and fallback_callback
            ):
                logger.info(
                    "%s [AssemblyAI] No final transcript received; "
                    "using latest partial as fallback: %s",
                    session.get_log_prefix(),
                    self._last_partial,
                )

                fallback_callback(
                    self._last_partial,
                    True,
                )

                self._last_partial = ""

        except websockets.exceptions.ConnectionClosed as exc:
            logger.error(
                "%s [AssemblyAI] force_end_turn failed because "
                "WebSocket is closed: %s",
                session.get_log_prefix(),
                exc,
            )

            raise STTConnectionError(
                f"AssemblyAI WebSocket closed during force_end_turn: {exc}"
            ) from exc

        except Exception as exc:
            logger.exception(
                "%s [AssemblyAI] force_end_turn failed",
                session.get_log_prefix(),
            )

            raise STTStreamingError(
                f"AssemblyAI force_end_turn failed: {exc}"
            ) from exc

    async def _emit_if_no_formatted(
        self,
        transcript: str,
        on_transcript: TranscriptCallback,
    ) -> None:
        """
        Emit an unformatted transcript if a formatted transcript
        does not arrive within the configured waiting period.
        """

        try:
            await asyncio.sleep(
                self.formatted_transcript_wait_ms / 1000
            )

            if self._pending_unformatted != transcript:
                logger.debug(
                    "%s [AssemblyAI] Skipping stale unformatted transcript",
                    session.get_log_prefix(),
                )
                return

            self._pending_unformatted = ""
            self._last_partial = ""

            logger.info(
                "%s [AssemblyAI] No formatted transcript arrived "
                "within %sms; emitting unformatted transcript: %s",
                session.get_log_prefix(),
                self.formatted_transcript_wait_ms,
                transcript,
            )

            on_transcript(transcript, True)

        except asyncio.CancelledError:
            logger.debug(
                "%s [AssemblyAI] Pending unformatted transcript "
                "task cancelled",
                session.get_log_prefix(),
            )
            raise