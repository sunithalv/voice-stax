# VoiceStax/core/audio_manager.py

"""
AudioManager: Handles TTS streaming with word-level timing for frontend synchronization.
"""

import base64
import asyncio
from typing import Any
from voicestax.core import timing
from voicestax.utils.exceptions import TTSError, AudioProcessingError, WebSocketError
from voicestax.utils.logger import logger


class AudioManager:
    """Manages TTS audio generation and streaming over WebSocket."""

    def __init__(self, tts_client: Any, sample_rate: int = 24000):
        self.tts_client = tts_client
        self.sample_rate = sample_rate

    def _is_cancelled(self, session, response_id: str) -> bool:
        """Single cancel check used throughout the stream."""
        return (
            session.cancel_event.is_set()
            or not session.is_speaking
            or response_id != session.current_response_id
        )

    async def stream_text(self, websocket, text: str, session):
        response_id = session.current_response_id
        session.is_speaking = True
        logger.info(f"[TTS] Starting stream for response_id={response_id}: {text[:60]}...")

        try:
            try:
                await websocket.send_json({"type": "clear_audio"})
            except Exception as e:
                raise WebSocketError(f"Failed to send clear_audio message: {e}") from e

            audio_chunks = []

            # ── 1. Stream TTS chunks ──────────────────────────────────────────
            # We run the synchronous TTS iterator in a thread so that
            # asyncio can remain responsive (cancel_event can be checked
            # between chunks even if the TTS provider is slow).
            loop = asyncio.get_event_loop()
            chunk_queue: asyncio.Queue = asyncio.Queue()

            async def _producer():
                """Push TTS chunks into the queue from a thread."""
                def _iterate():
                    try:
                        for chunk in self.tts_client.stream_tts(text=text):
                            chunk_queue.put_nowait(chunk)
                    finally:
                        chunk_queue.put_nowait(None)  # sentinel

                await loop.run_in_executor(None, _iterate)

            producer_task = asyncio.create_task(_producer())

            while True:
                # Yield to event loop so cancel_event can be set by
                # a concurrent handle_user_message call.
                chunk = await chunk_queue.get()

                if chunk is None:
                    # TTS generator exhausted normally
                    break

                if self._is_cancelled(session, response_id):
                    logger.info("[TTS] Barge-in detected mid-stream — aborting")
                    producer_task.cancel()
                    return  # ← exit without sending complete/words

                audio_chunks.append(chunk)
                try:
                    encoded_audio = base64.b64encode(chunk).decode()
                except Exception as e:
                    raise AudioProcessingError(f"Failed to encode audio chunk: {e}") from e
                try:
                    await websocket.send_json({
                        "type": "audio_chunk",
                        "audio": encoded_audio,
                        "response_id": response_id,
                    })
                except Exception as e:
                    raise WebSocketError(f"Failed to send audio chunk: {e}") from e

            await producer_task  # ensure thread is cleaned up

            # ── 2. Final cancel guard before complete ─────────────────────────
            if self._is_cancelled(session, response_id):
                logger.info("[TTS] Cancelled before complete — aborting")
                return

            try:
                await websocket.send_json({
                    "type": "complete",
                    "full_text": text,
                    "response_id": response_id,
                })
            except Exception as e:
                raise WebSocketError(f"Failed to send complete message: {e}") from e
            session.ignore_barge_in_once = True  # ← only on natural completion

            # ── 3. Word timing (runs concurrently with frontend playback) ─────
            # Words are sent AFTER complete so the frontend has audio buffered.
            # Each word is gated on the same cancel check.
            try:
                combined_audio = b"".join(audio_chunks)
                delay_per_word_ms = timing.calculate_word_delays(combined_audio, text=text)
            except Exception as e:
                raise AudioProcessingError(f"Failed to process audio for timing: {e}") from e
            words = text.split()

            for i, word in enumerate(words):
                if self._is_cancelled(session, response_id):
                    return

                try:
                    await websocket.send_json({
                        "type": "word",
                        "word": word,
                        "index": i,
                        "total": len(words),
                        "response_id": response_id,
                    })
                except Exception as e:
                    raise WebSocketError(f"Failed to send word timing: {e}") from e
                await asyncio.sleep(delay_per_word_ms / 1000)

        except asyncio.CancelledError:
            logger.info("[TTS] stream_text task cancelled")
        except Exception as e:
            logger.error(f"[TTS ERROR]: {e}")
            raise TTSError(f"TTS streaming failed: {e}") from e
        finally:
            if response_id == session.current_response_id:
                session.is_speaking = False
                session.set_state("idle")