# Summary: This module manages TTS audio generation and streaming for voice sessions.
# It coordinates chunked audio delivery over WebSocket, STT muting during playback,
# cancellation handling, and format conversion for browser playback.

import base64
import asyncio
import time
from voicestax.providers.stt.base import BaseSTTProvider
from voicestax.providers.tts.base import BaseTTSProvider
from voicestax.utils.exceptions import TTSError, AudioProcessingError, WebSocketError
from voicestax.utils.logger import logger


class AudioManager:
    """Manages TTS audio generation and streaming over WebSocket."""

    def __init__(self, tts_client: BaseTTSProvider, stt_client: BaseSTTProvider):
        self.tts_client = tts_client
        self.stt_client = stt_client

    # Check if the current TTS session has been cancelled due to barge-in or other conditions.
    def _is_cancelled(self, session, response_id):
        # Determine if the TTS session should be cancelled based on the session state and response ID.
        cancelled = (
            session.cancel_event.is_set()
            or not session.is_speaking
            or response_id != session.current_response_id
        )

        if cancelled:
            logger.info(
                "%s TTS cancelled: response_id=%s current_response_id=%s",
                session.log_prefix(),
                response_id,
                session.current_response_id,
            )

        return cancelled
    
    
    def _calculate_word_delay(
        self,
        audio_bytes: bytes,
        sample_rate: int = 24000,
        channels: int = 1,
        sample_width: int = 2,
        text: str = ""
    ) -> int:
        """
        Approximate per-word delay in milliseconds for streaming TTS audio.
        """
        if not text or not audio_bytes:
            return 0

        duration_sec = len(audio_bytes) / (sample_rate * channels * sample_width)
        words = text.split()
        return int((duration_sec * 1000) / max(len(words), 1))
    
    # Stream text to the client via WebSocket, handling TTS generation, chunking, and STT muting.
    async def stream_text(self, websocket, text: str, session):
        # Ignore empty messages
        if not text.strip():
            return
        response_id = session.current_response_id
        session.is_speaking = True
        session.tts_start_time = time.perf_counter()
        session.tts_first_chunk_time = 0.0
        
        logger.info(
            "%s [TTS] Started response_id=%s chars=%d format=%s",
            session.log_prefix(),
            response_id,
            len(text),
            getattr(self.tts_client, "output_format", None),
        )
        

        # PCM output (e.g. pcm_24000) is streamed chunk-by-chunk to the client
        # for real-time playback. Raw PCM int16 audio is base64-encoded here;
        # any conversion required for Web Audio playback happens client-side.
        # MP3 chunks are buffered client-side until `complete`.
        is_pcm = str(getattr(self.tts_client, 'output_format', '') or '').lower().startswith('pcm_')
        logger.info(
            "%s [TTS] Streaming mode: %s",
            session.log_prefix(),
            "realtime PCM" if is_pcm else "buffered compressed audio",
        )
        # ── Mute STT as soon as TTS begins ───────────────────────────────────
        if self.stt_client:
            self.stt_client.mute()
            
        try:
            try:
                # Clear any previous audio on the client before starting new TTS streaming.
                await websocket.send_json({"type": "clear_audio"})
            except Exception as e:
                raise WebSocketError(f"Failed to send clear_audio message: {e}") from e

            audio_chunks = []

            # ── 1. Stream TTS chunks ──────────────────────────────────────────
            # We run the synchronous TTS iterator in a thread so that
            # asyncio can remain responsive (cancel_event can be checked
            # between chunks even if the TTS provider is slow).
            loop = asyncio.get_running_loop()
            chunk_queue: asyncio.Queue = asyncio.Queue()

            async def _producer():
                """Push TTS chunks into the queue from a thread."""
                def _iterate():
                    try:
                        # Returns an iterator of audio chunks
                        response = self.tts_client.stream_tts(text=text)
                        
                        logger.debug(
                            "%s [TTS] TTS response type: %s",
                            session.log_prefix(),
                            type(response),
                        )

                        # Iterates synchronous response, puts chunks into the asyncio queue
                        for chunk in response:
                            # Schedules work on asyncio event loop in a thread-safe way and
                            # places the chunk into an asyncio.Queue immediately, without awaiting.
                            loop.call_soon_threadsafe(
                                chunk_queue.put_nowait,
                                chunk
                            )

                    except Exception as e:
                        logger.error(
                            "%s [TTS] TTS iteration failed: %s",
                            session.log_prefix(),
                            e,
                        )
                        # On exception, put the exception into the queue so it can be raised in the async context.
                        loop.call_soon_threadsafe(
                            chunk_queue.put_nowait,
                            e
                        )

                    finally:
                        # On normal completion, signal the end of the stream by putting None into the queue.
                        loop.call_soon_threadsafe(
                            chunk_queue.put_nowait,
                            None
                        )
                # Runs the synchronous TTS iterator in separate thread to avoid blocking the event loop.
                await loop.run_in_executor(None, _iterate)
                
            # Create a task to run the producer coroutine that will fill the chunk_queue with audio chunks.
            producer_task = asyncio.create_task(_producer())

            while True:
                # Yield to event loop so cancel_event can be set by
                # a concurrent handle_user_message call.
                chunk = await chunk_queue.get()
                
                # If the chunk is an exception, raise it to propagate the error to the async context.
                if isinstance(chunk, Exception):
                    raise TTSError(f"TTS provider failed: {chunk}")

                if chunk is None:
                    # TTS generator exhausted normally
                    logger.debug(
                        "%s [TTS] Audio stream generation completed",
                        session.log_prefix(),
                    )
                    break
                
                # Record the time of the first chunk for latency metrics
                if session.tts_first_chunk_time == 0.0:
                    session.tts_first_chunk_time = time.perf_counter()

                    tts_latency = (
                        session.tts_first_chunk_time
                        - session.tts_start_time
                    ) * 1000

                    session.record_latency(
                        "tts_latency",
                        round(tts_latency, 2)
                    )
                    
                    # End-to-end turn latency ie from end of user speech to first TTS chunk
                    if session.speech_end_time and session.tts_first_chunk_time:
                        total_turn_latency = (
                            session.tts_first_chunk_time
                            - session.speech_end_time
                        ) * 1000

                        session.record_latency(
                            "total_turn_latency",
                            round(total_turn_latency, 2)
                        )

                        logger.info(
                            "%s [LATENCY] Total turn latency: %.2f ms",
                            session.log_prefix(),
                            total_turn_latency,
                        )
                
                # Check for cancellation (barge-in) before sending each chunk
                if self._is_cancelled(session, response_id):
                    logger.info("%s [TTS] Barge-in detected mid-stream — aborting", session.log_prefix())
                    producer_task.cancel()
                    return  # ← exit without sending complete/words

                if not is_pcm:
                    audio_chunks.append(chunk)
                try:
                    # Encode the audio chunk to base64 for WebSocket transmission
                   encoded_audio = base64.b64encode(chunk).decode()
                except Exception as e:
                    raise AudioProcessingError(f"Failed to encode audio chunk: {e}") from e
                try:
                    logger.debug(
                        "%s [TTS] Sending audio chunk: %d bytes",
                        session.log_prefix(),
                        len(chunk),
                    )
                    
                    await websocket.send_json({
                        "type": "audio_chunk",
                        "audio": encoded_audio,
                        "encoding": "pcm_s16le" if is_pcm else "mp3",
                        "response_id": response_id,
                    })
                except Exception as e:
                    raise WebSocketError(f"Failed to send audio chunk: {e}") from e

            await producer_task  # ensure thread is cleaned up

            # ── 2. Final cancel guard before complete ─────────────────────────
            if self._is_cancelled(session, response_id):
                logger.info("%s [TTS] Cancelled before complete — aborting", session.log_prefix())
                return

            # ── 3. Send word messages and complete event ───────────────────────
            words = text.split()

            if is_pcm:
                # ── PCM path ─────────────────────────────────────────────────
                # Audio has been playing on the client in real-time as chunks
                # arrived. Send all word messages BEFORE `complete` so they are
                # already queued when the client calls finaliseStream().
                # No per-word delays needed — finaliseStream() reveals them all
                # at once, timed to when the audio was already playing.
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
                        raise WebSocketError(f"Failed to send word (PCM): {e}") from e
 
                # ── 4. Send complete event ─────────────────────────────────────────
                try:
                    logger.info(
                        "%s [TTS] PCM stream complete; sending completion event",
                        session.log_prefix(),
                    )
                    await websocket.send_json({
                        "type": "complete",
                        "full_text": text,
                        "response_id": response_id,
                        "encoding": "pcm_s16le",
                    })

                except Exception as e:
                    raise WebSocketError(f"Failed to send complete message: {e}") from e

            else:
                # ── mp3 path ──────────────────────────────────────────────────
                # Client buffers all mp3 chunks and only starts playback on
                # `complete`. Send complete first so playback begins immediately,
                # then stream words with per-word delays to sync with audio.
                try:
                    logger.info(
                        "%s [TTS] MP3 generation complete; starting buffered playback",
                        session.log_prefix(),
                    )

                    await websocket.send_json({
                        "type": "complete",
                        "full_text": text,
                        "response_id": response_id,
                         "encoding": "mp3",
                    })
                except Exception as e:
                    raise WebSocketError(f"Failed to send complete message: {e}") from e

                try:
                    combined_audio = b"".join(audio_chunks)
                    delay_per_word_ms = self._calculate_word_delay(combined_audio, text=text)
                except Exception as e:
                    raise AudioProcessingError(f"Failed to process audio for timing: {e}") from e

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

            session.ignore_barge_in_once = True  # ← only on natural completion
            logger.info("%s [TTS] completed",session.log_prefix())

        except asyncio.CancelledError:
            logger.info("%s [TTS] stream_text task cancelled", session.log_prefix())
        except TTSError:
            raise
        except Exception as e:
            logger.error(
                "%s [TTS ERROR]: %s",
                session.log_prefix(),
                e,
            )
            raise TTSError(f"TTS streaming failed: {e}") from e
        finally:
            if response_id == session.current_response_id:
                session.is_speaking = False
                session.set_state("idle")

            # ── Unmute STT after TTS ends (barge-in, completion, or error) ───
            # The 200ms buffer lets any room echo from the speakers decay
            # before STT starts listening again.
            if self.stt_client:
                await asyncio.sleep(0.2)
                self.stt_client.unmute()