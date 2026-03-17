from voicestax.providers.stt.base import BaseSTTProvider
from voicestax.utils.exceptions import STTError, STTConnectionError, STTStreamingError
import asyncio
import websockets
import json
from typing import Callable, Optional
from voicestax.utils.logger import logger


class AssemblyAISTTProvider(BaseSTTProvider):

    def __init__(self, api_key: str, sample_rate: int = 16000, encoding: Optional[str] = None):
        self.api_key = api_key
        self.sample_rate = sample_rate
        self.encoding = encoding or "pcm_s16le"

        self._is_listening = False
        self.is_streaming = False
        self._last_partial = ""
        self._pending_unformatted = ""
        self._pending_unformatted_task = None

        self._ws = None
        self._stream_task: Optional[asyncio.Task] = None
        self._cancel_event = asyncio.Event()
        self._send_lock = asyncio.Lock()

    @property
    def is_ready(self) -> bool:
        return self.is_streaming

    def validate_api_key(self) -> bool:
        return bool(self.api_key)

    def is_listening(self) -> bool:
        return self._is_listening

    async def send_audio(self, audio_chunk: bytes):
        # AssemblyAI v3: send raw binary bytes directly.
        # Do NOT base64-encode or JSON-wrap -- that causes 3006 Invalid Message Type.
        if not self.is_streaming or not self._ws or not self._is_listening:
            return

        async with self._send_lock:
            try:
                await self._ws.send(audio_chunk)
            except websockets.exceptions.ConnectionClosed as e:
                logger.error(f"[AssemblyAI] WS closed during send: {e}")
                self.is_streaming = False
                self._is_listening = False 
                raise STTConnectionError(f"WebSocket connection closed: {e}") from e
            except Exception as e:
                logger.error(f"[AssemblyAI] Audio send failed: {e}")
                raise STTStreamingError(f"Failed to send audio: {e}") from e

    def start_streaming(self, on_transcript, on_error):
        if self._is_listening:
            return
        self._is_listening = True
        self.is_streaming = False
        self._cancel_event.clear()
        self._stream_task = asyncio.create_task(self._run_stream(on_transcript, on_error))

    def stop_streaming(self):
        self._is_listening = False
        self.is_streaming = False
        self._cancel_event.set()
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()

    async def _run_stream(self, on_transcript, on_error):
        url = (
            f"wss://streaming.assemblyai.com/v3/ws"
            f"?sample_rate={self.sample_rate}"
            f"&encoding={self.encoding}"
            f"&format_turns=true"
            f"&end_of_turn_confidence_threshold=0.5"  # ← default is 0.7, lower = faster
            f"&min_end_of_turn_silence_when_confident=400"  # ← ms, default 700
        )
        headers = {"Authorization": self.api_key}
        logger.info(f"[AssemblyAI] Connecting: {url}")

        try:
            async with websockets.connect(url, additional_headers=headers, ping_interval=10, ping_timeout=20) as ws:
                self._ws = ws
                self.is_streaming = True
                logger.info("[AssemblyAI] Connected")

                while self._is_listening:
                    cancel_task = asyncio.create_task(self._cancel_event.wait())
                    recv_task = asyncio.create_task(ws.recv())

                    done, pending = await asyncio.wait([recv_task, cancel_task], return_when=asyncio.FIRST_COMPLETED)

                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                    if cancel_task in done:
                        logger.info("[AssemblyAI] Cancelled")
                        try:
                            await ws.send(json.dumps({"terminate_session": True}))
                        except Exception:
                            pass
                        break

                    if recv_task in done:
                        try:
                            message = recv_task.result()
                        except websockets.exceptions.ConnectionClosed as e:
                            on_error(STTError(f"Connection closed: {e}"))
                            break
                        except Exception as e:
                            on_error(STTStreamingError(f"Receive failed: {e}"))
                            break

                        try:
                            data = json.loads(message)
                        except (json.JSONDecodeError, TypeError):
                            continue

                        logger.debug(f"[AssemblyAI] <- {data}")
                        msg_type = data.get("type", "")

                        if msg_type == "Begin":
                            logger.info(f"[AssemblyAI] Session began: {data.get('id')}")
                            continue

                        if msg_type == "Turn":
                            is_final = data.get("end_of_turn", False)
                            transcript = data.get("transcript", "").strip()
                            turn_is_formatted = data.get("turn_is_formatted", False)
                            
                            if is_final and transcript:
                                if turn_is_formatted:
                                    if self._pending_unformatted_task and not self._pending_unformatted_task.done():
                                        self._pending_unformatted_task.cancel()
                                        self._pending_unformatted_task = None
                                    self._pending_unformatted = ""
                                    # Always use formatted turn — cancel any pending unformatted
                                    logger.info(f"[AssemblyAI] Turn (formatted final): {transcript}")
                                    self._last_partial = ""
                                    on_transcript(transcript, True)
                                else:
                                    # Unformatted — store it but wait 300ms for formatted version
                                    logger.debug(f"[AssemblyAI] Turn (unformatted) — waiting for formatted: {transcript}")
                                    self._pending_unformatted = transcript
                                    self._pending_unformatted_task = asyncio.create_task(
                                        self._emit_if_no_formatted(transcript, on_transcript)
                                    )
                            continue

                        if msg_type == "PartialTranscript":
                            text = data.get("text", "").strip()
                            if text:
                                self._last_partial = text  # track latest partial
                                on_transcript(text, False)
                            continue

                        if msg_type == "SessionTerminated":
                            break

                        if msg_type == "error" or "error" in data:
                            err_msg = data.get("error", str(data))
                            logger.error(f"[AssemblyAI] Error: {err_msg}")
                            on_error(STTError(err_msg))
                            break

        except Exception as e:
            logger.error(f"[AssemblyAI] Stream error: {type(e).__name__}: {e}")
            on_error(STTStreamingError(f"Streaming failed: {e}"))
        finally:
            self._is_listening = False
            self.is_streaming = False
            self._ws = None
            logger.info("[AssemblyAI] WebSocket closed")
    
    async def force_end_turn(self, fallback_callback=None):
        if self._ws and self.is_streaming:
            try:
                await self._ws.send(json.dumps({"type": "ForceEndpoint"}))
                logger.info("[AssemblyAI] Forced end of turn")
                
                # Store partial now — if a Turn fires during sleep it clears _last_partial
                partial_at_interrupt = self._last_partial
                await asyncio.sleep(0.3)
                
                # Only emit if no Turn arrived (Turn handler clears _last_partial)
                if self._last_partial and self._last_partial == partial_at_interrupt and fallback_callback:
                    logger.info(f"[AssemblyAI] Using last partial as fallback: {self._last_partial}")
                    fallback_callback(self._last_partial, True)
                    self._last_partial = ""
            except Exception as e:
                logger.error(f"[AssemblyAI] force_end_turn failed: {e}")
                raise STTStreamingError(f"Force end turn failed: {e}") from e
    
    async def _emit_if_no_formatted(self, transcript: str, on_transcript):
        """Wait briefly — if no formatted turn arrives, emit the unformatted one."""
        await asyncio.sleep(0.35)
        if self._pending_unformatted == transcript:
            logger.info(f"[AssemblyAI] No formatted turn arrived — using unformatted: {transcript}")
            self._pending_unformatted = ""
            on_transcript(transcript, True)