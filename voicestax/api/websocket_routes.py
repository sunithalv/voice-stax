# WebSocket routes for the voice assistant.
# This file manages real-time chat connections, initializes speech and language providers,
# streams audio/text between the client and the agent, and maintains session state.

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
import asyncio
import json
import math
import struct
import time
from collections import deque
from voicestax.session.voice_session import SessionData
from voicestax.core.voice_agent import VoiceAgent
from voicestax.core.chat_engine import ChatEngine
from voicestax.core.audio_manager import AudioManager
from voicestax.core.vad_manager import VADManager
from voicestax.config.settings import VoiceSettings  
from voicestax.providers.stt.factory import get_stt_provider
from voicestax.providers.tts.factory import get_tts_provider
from voicestax.providers.llm.factory import get_llm_provider
from voicestax.providers.vad.factory import get_vad_provider
from voicestax.utils.exceptions import ProviderInitializationError, WebSocketError, WebSocketConnectionError,TTSError, STTConnectionError
from voicestax.utils.logger import logger


# Creates the WebSocket router for the voice chat endpoint.
def create_router(settings: VoiceSettings, custom_llm_provider=None) -> APIRouter:
    """
    Returns a configured APIRouter with the given settings baked in.
    Called once by create_voice_app() — settings are captured via closure.
    """
    router = APIRouter()

    # ── WebSocket endpoint for real-time voice chat ─────────────────────────────
    @router.websocket("/ws/chat")
    async def websocket_endpoint(websocket: WebSocket):
        try:
            await websocket.accept()
            logger.info("✅ WebSocket connected")
        except Exception as e:
            raise WebSocketConnectionError(f"Failed to establish WebSocket connection: {e}") from e

        # Initialize session state and providers
        session = SessionData(settings=settings)
        log_prefix=session.log_prefix()
        logger.info("%s Session started", log_prefix)

        agent = None
        conversation_started = False

        first_speaker = settings.first_speaker or "assistant"
        # Determine the greeting message based on the first speaker configuration
        greeting_message = (
            settings.initial_message if first_speaker == "assistant" else None
        )

        early_audio_buffer = []
        stt_accepting = False

        try:
            # Initialize providers based on settings
            stt_provider = get_stt_provider(
                provider_name=settings.stt_provider,
                api_key=settings.get_api_key("stt"),
                log_prefix=log_prefix,
                **settings.stt_config
            )
            logger.info("%s STT initialized", log_prefix)

            llm_provider = custom_llm_provider or get_llm_provider(
                provider_name=settings.llm_provider,
                api_key=settings.get_api_key("llm"),
                log_prefix=log_prefix,
                **settings.llm_config,
            )
            logger.info("%s LLM initialized", log_prefix)
            
            tts_provider = get_tts_provider(
                provider_name=settings.tts_provider,
                api_key=settings.get_api_key("tts"),
                log_prefix=log_prefix,
                **settings.tts_config,
            )
            logger.info("%s TTS initialized", log_prefix)
 
            # Add the providers to the session for later use
            session.stt_provider = stt_provider
            session.llm_provider = llm_provider

            audio_manager = AudioManager(
                tts_client=tts_provider,
                stt_client=stt_provider
            )
            logger.info("%s Audio manager initialized", log_prefix)
            
            # Add the audio manager and voice configuration to the session
            session.tts_provider = audio_manager

            # Initialize the voice agent with the session, audio manager, and chat engine
            agent = VoiceAgent(
                session=session,
                audio_manager=audio_manager,
                chat_engine=ChatEngine(llm_provider)
            )
            
            logger.info(
                "%s Voice session initialized successfully",
                log_prefix,
            )

            # Initialize VAD
            vad = get_vad_provider(
                provider_name=settings.vad_provider,
                log_prefix=log_prefix,
                **settings.vad_config,
            )
            
            vad_sample_rate = vad.sample_rate
            frame_duration_ms = vad.frame_duration_ms
            
            #Calculate framesize based on sample rate,frame duration for PCM 16 (2 bytes per sample)
            FRAME_SIZE = (
                vad_sample_rate
                * frame_duration_ms
                // 1000
                * 2
            )
            
            logger.info(
                "%s VAD frame size: %d bytes (%d ms @ %d Hz)",
                log_prefix,
                FRAME_SIZE,
                frame_duration_ms,
                vad_sample_rate,
            )

            #Stores raw PCM until there is enough data for one VAD frame (640 bytes).
            vad_buffer = bytearray()
            #Stores speech frames that will be sent to stt.
            stt_send_buffer = bytearray()
            
            barge_in_confirmed = False
            
            # Initialize the VADManager with the configured thresholds and durations
            vad_manager = VADManager(
                silence_threshold_ms=settings.vad_silence_threshold_ms, 
                frame_duration_ms=frame_duration_ms,
                max_utterance_ms=settings.vad_max_utterance_ms  
            )
            
            try:
                # Send a system_ready message to the frontend to indicate that the system is ready for interaction
                await websocket.send_json({"type": "system_ready"})
            except Exception as e:
                raise WebSocketError(f"Failed to send system_ready: {e}") from e

        except Exception as e:
            logger.error(f"❌ Initialization error: {e}")
            raise ProviderInitializationError(f"Failed to initialize providers: {e}") from e

        # Helper functions for sending messages to the frontend and handling transcripts/errors
        async def send_transcription(text: str):
            try:
                # Send the user transcription to the frontend for display
                await websocket.send_json({
                    "type": "transcript",
                    "speaker": "user",
                    "text": text
                })
            except Exception as e:
                logger.error(f"WebSocket error sending transcription: {e}")
        # Helper function to send error messages to the frontend
        async def send_error_message(message: str):
            try:
                await websocket.send_json({"type": "error", "message": message})
            except Exception as e:
                logger.error(f"WebSocket error sending error message: {e}")
                
        async def _process_final_transcript(
            text: str,
            speech_end_time: float,
            stt_final_time: float,
        ) -> None:
            """Process a final STT transcript in a predictable order."""

            try:
                # Send the recognized user transcript to the browser first.
                await send_transcription(text)

            except Exception:
                logger.exception(
                    "%s Failed to send user transcription",
                    log_prefix,
                )

            # Continue processing even if displaying the transcript failed.
            await _handle_message(text, speech_end_time, stt_final_time)

        # Events from local VAD and AssemblyAI can arrive in either order.
        # Pair them in FIFO order before processing a final transcript.
        pending_speech_end_times = deque()
        pending_final_transcripts = deque()

        def _dispatch_paired_transcripts() -> None:
            """Dispatch final transcripts only when a VAD end timestamp exists."""

            while (
                pending_speech_end_times
                and pending_final_transcripts
            ):
                speech_end_time = pending_speech_end_times.popleft()
                text, stt_final_time = pending_final_transcripts.popleft()

                logger.info(
                    "%s [STT] Pairing final transcript with VAD speech end",
                    log_prefix,
                )

                asyncio.create_task(
                    _process_final_transcript(
                        text,
                        speech_end_time,
                        stt_final_time,
                    )
                )

        # Callback for receiving transcripts from the STT provider.
        def on_transcript(text: str, is_final: bool) -> None:
            """Queue final transcripts until their VAD timestamps are available."""

            if not text or not is_final:
                return

            stt_final_time = time.perf_counter()

            pending_final_transcripts.append(
                (text, stt_final_time)
            )

            logger.info(
                "%s [STT] Final transcript received: %s",
                log_prefix,
                text,
            )

            logger.debug(
                "%s [STT] Pending final transcripts=%d | "
                "Pending speech-end timestamps=%d",
                log_prefix,
                len(pending_final_transcripts),
                len(pending_speech_end_times),
            )

            _dispatch_paired_transcripts()
        
        # Callback for handling errors from the STT provider
        stt_reconnecting = False

        async def _reconnect_stt() -> None:
            """Re-open the STT stream after the provider connection drops."""
            nonlocal stt_reconnecting
            if stt_reconnecting:
                return
            stt_reconnecting = True
            try:
                for attempt in range(1, 4):
                    # Let the old stream task finish its cleanup first.
                    old_task = getattr(session.stt_provider, "_stream_task", None)
                    if old_task is not None and not old_task.done():
                        try:
                            await asyncio.wait_for(asyncio.shield(old_task), 5)
                        except Exception:
                            pass

                    logger.warning(
                        "%s [STT] Reconnecting (attempt %d/3)",
                        log_prefix,
                        attempt,
                    )
                    session.stt_provider.start_streaming(
                        on_transcript=on_transcript,
                        on_error=on_error,
                    )

                    for _ in range(300):
                        if session.stt_provider.is_ready:
                            break
                        await asyncio.sleep(0.05)

                    if session.stt_provider.is_ready:
                        logger.info("%s [STT] Reconnected", log_prefix)
                        return

                    await asyncio.sleep(attempt)

                logger.error("%s [STT] Reconnect failed", log_prefix)
            finally:
                stt_reconnecting = False

        def on_error(e: Exception):
            asyncio.create_task(send_error_message(str(e)))
            if isinstance(e, STTConnectionError) and conversation_started:
                asyncio.create_task(_reconnect_stt())

        # Helper function to handle user messages, send them to the agent, and manage session state
        async def _handle_message(
            text: str,
            speech_end_time: float,
            stt_final_time: float,
        ):
            nonlocal stt_accepting, conversation_started
            logger.info(
                "%s User message received: %s",
                log_prefix,
                text,
            )
            if speech_end_time > 0:
                session.start_turn_latency(
                    speech_end_time,
                    stt_final_time,
                )
            else:
                # Keep the turn metrics valid without reporting a false STT latency.
                logger.warning(
                    "%s [STT] Cannot calculate STT latency: "
                    "speech-end timestamp is unavailable",
                    log_prefix,
                )

                session.start_turn_latency(
                    stt_final_time,
                    stt_final_time,
                )

            stt_latency = (
                stt_final_time - speech_end_time
            ) * 1000 if speech_end_time > 0 else 0.0
                
            logger.info(
                "%s [STT] Final transcript received: %s | latency=%.2f ms",
                session.log_prefix(),
                text,
                stt_latency,
            )

            try:
                await agent.handle_user_message(text, websocket)
            finally:
                metrics = session.finish_turn_latency()
                logger.info(
                    "%s LATENCY | STT=%.2fms | LLM=%.2fms | TTS=%.2fms | TOTAL=%.2fms",
                    log_prefix,
                    metrics.get("stt_latency", 0),
                    metrics.get("llm_latency", 0),
                    metrics.get("tts_latency", 0),
                    metrics.get("total_turn_latency", 0),
                )

            if agent.session_ended:
                logger.info(
                    "%s Session end detected - cleaning up",
                    log_prefix,
                )
                stt_accepting = False
                conversation_started = False
                agent.reset_session_ended()
                try:
                    session.stt_provider.stop_streaming()
                except Exception as e:
                    logger.warning(
                        "%s STT stop error: %s",
                        log_prefix,
                        e,
                    )
                session.reset_session()

                try:
                    await websocket.send_json({"type": "session_ended"})
                except Exception as e:
                    raise WebSocketError(f"Failed to send session_ended: {e}") from e

        # Process incoming PCM audio through VAD, stream detected speech
        # frames to STT in batches, handle speech state transitions and
        # barge-in, and finalize the STT turn when the utterance ends.
        barge_in_speech_frames = 0
        # Speech frames seen since the last ForceEndpoint. Short bursts
        # (coughs, clicks, speaker echo) should not finalize the STT turn,
        # otherwise real sentences get chopped into fragments like "Oh."
        endpoint_speech_frames = 0
        MIN_ENDPOINT_SPEECH_FRAMES = 10  # 200 ms at 20 ms frames
        BARGE_IN_MIN_FRAMES = 25  # 500 ms of sustained speech to interrupt TTS
        barge_in_rms_response_key = None
        barge_in_rms_stats = {
            "speech": {"count": 0, "sum": 0.0, "min": None, "max": None},
            "non_speech": {"count": 0, "sum": 0.0, "min": None, "max": None},
        }
        
        # RMS calculation for little-endian signed PCM16 audio
        def _pcm16_frame_rms(frame: bytes) -> float:
            """Return linear RMS for one little-endian signed PCM16 frame."""
            sample_count = len(frame) // 2
            if sample_count == 0:
                return 0.0
            sum_squares = sum(
                sample * sample
                for (sample,) in struct.iter_unpack("<h", frame[:sample_count * 2])
            )
            return math.sqrt(sum_squares / sample_count)

        def _log_and_reset_barge_in_rms(reason: str) -> None:
            """Log one response-period snapshot, then clear it atomically."""
            speech = barge_in_rms_stats["speech"]
            non_speech = barge_in_rms_stats["non_speech"]
            response_key = barge_in_rms_response_key
            if response_key is None:
                return

            def _formatted_stats(stats):
                if not stats["count"]:
                    return "n/a", "n/a", "n/a"
                return (
                    f"{stats['min']:.2f}",
                    f"{stats['max']:.2f}",
                    f"{stats['sum'] / stats['count']:.2f}",
                )

            speech_min, speech_max, speech_avg = _formatted_stats(speech)
            non_speech_min, non_speech_max, non_speech_avg = _formatted_stats(non_speech)
            try:
                logger.info(
                    "%s [BARGE-IN RMS SHADOW] event=%s response_id=%s "
                    "tts_generation=%s vad_positive_frames=%d "
                    "vad_positive_rms_min_pcm16_lsb=%s "
                    "vad_positive_rms_max_pcm16_lsb=%s "
                    "vad_positive_rms_avg_pcm16_lsb=%s vad_negative_frames=%d "
                    "vad_negative_rms_min_pcm16_lsb=%s "
                    "vad_negative_rms_max_pcm16_lsb=%s "
                    "vad_negative_rms_avg_pcm16_lsb=%s",
                    log_prefix,
                    reason,
                    response_key[0],
                    response_key[1],
                    speech["count"],
                    speech_min,
                    speech_max,
                    speech_avg,
                    non_speech["count"],
                    non_speech_min,
                    non_speech_max,
                    non_speech_avg,
                )
            finally:
                _reset_barge_in_rms_stats()

        def _reset_barge_in_rms_stats() -> None:
            nonlocal barge_in_rms_response_key
            barge_in_rms_response_key = None
            for stats in barge_in_rms_stats.values():
                stats["count"] = 0
                stats["sum"] = 0.0
                stats["min"] = None
                stats["max"] = None

        def _add_barge_in_rms(is_speech: bool, frame_rms: float) -> None:
            stats = barge_in_rms_stats["speech" if is_speech else "non_speech"]
            stats["count"] += 1
            stats["sum"] += frame_rms
            stats["min"] = frame_rms if stats["min"] is None else min(stats["min"], frame_rms)
            stats["max"] = frame_rms if stats["max"] is None else max(stats["max"], frame_rms)

        # Strong references so background endpoint tasks aren't garbage-collected.
        endpoint_tasks: set[asyncio.Task] = set()       

        async def _force_end_turn() -> None:
            force_endpoint_start = time.perf_counter()
            try:
                await session.stt_provider.force_end_turn(
                    fallback_callback=on_transcript
                )
            except Exception:
                logger.exception(
                    "%s [STT] ForceEndpoint failed",
                    log_prefix,
                )
                return

            logger.info(
                "%s [STT] ForceEndpoint call completed: %.2f ms",
                log_prefix,
                (time.perf_counter() - force_endpoint_start) * 1000,
            )
        
        # Helper function to check if STT can receive audio (ready and not muted)
        def _stt_can_receive_audio() -> bool:
            return (
                session.stt_provider.is_ready
                and not session.stt_provider.is_muted
            )

        # Wait for STT to become unmuted and ready after a barge-in event, with a timeout.
        async def _wait_for_stt_ready_after_barge_in(
            timeout: float = 3.0,
        ) -> bool:
            deadline = asyncio.get_running_loop().time() + timeout

            while asyncio.get_running_loop().time() < deadline:
                if _stt_can_receive_audio():
                    return True

                await asyncio.sleep(0.01)

            logger.warning(
                "%s [STT] Timed out waiting for STT to become unmuted and ready",
                log_prefix,
            )
            return False

        async def send_audio_to_stt(pcm_bytes: bytes):
            nonlocal barge_in_speech_frames
            nonlocal endpoint_speech_frames
            nonlocal barge_in_confirmed
            nonlocal barge_in_rms_response_key
            try:
                
                # Process through VAD
                vad_buffer.extend(pcm_bytes)
                
                while len(vad_buffer) >= FRAME_SIZE:
                    frame = bytes(vad_buffer[:FRAME_SIZE])
                    del vad_buffer[:FRAME_SIZE]

                    is_speech = vad.is_speech(frame)

                    events = vad_manager.process_frame(is_speech)

                    # Shadow telemetry is scoped to one TTS response generation.
                    # It observes every incoming frame while speaking, without
                    # affecting VAD, the candidate counter, or audio forwarding.
                    assistant_speaking = (
                        session.state == "speaking" and session.is_speaking
                    )
                    if assistant_speaking:
                        response_key = (
                            session.current_response_id,
                            session.tts_generation,
                        )
                        if (
                            barge_in_rms_response_key is not None
                            and response_key != barge_in_rms_response_key
                        ):
                            _log_and_reset_barge_in_rms(
                                "response_generation_changed"
                            )
                        barge_in_rms_response_key = response_key
                        _add_barge_in_rms(
                            is_speech,
                            _pcm16_frame_rms(frame),
                        )
                    elif barge_in_rms_response_key is not None:
                        _log_and_reset_barge_in_rms("assistant_stopped")

                    # Buffer speech audio for STT.
                    if is_speech:
                        endpoint_speech_frames += 1
                        stt_send_buffer.extend(frame)

                        if (len(stt_send_buffer) >= 3200
                            and _stt_can_receive_audio()):
                            logger.debug(
                                "%s Sending %d bytes to STT",
                                log_prefix,
                                len(stt_send_buffer),
                            )

                            await session.stt_provider.send_audio(
                                bytes(stt_send_buffer)
                            )

                            stt_send_buffer.clear()
                    # Speech-start event: log the transition.
                    if "speech_started" in events:
                        # A new utterance began; drop the previous end time so
                        # latency metrics are never measured from a stale one.
                        session.speech_end_time = 0.0
                        logger.info(
                            "%s [VAD] Speech started state=%s",
                            log_prefix,
                            session.state,
                        )

                    # Count consecutive speech frames only while TTS is playing.
                    if (
                        session.state == "speaking"
                        and session.is_speaking
                        and is_speech
                    ):
                        barge_in_speech_frames += 1
                    else:
                        # Any silence or non-speaking state breaks the sequence.
                        barge_in_speech_frames = 0
                    
                    # Require sustained speech before interrupting TTS.
                    # For 20 ms VAD frames, 25 frames = 500 ms.
                    if (
                        session.state == "speaking"
                        and session.is_speaking
                        and barge_in_speech_frames >= BARGE_IN_MIN_FRAMES
                    ):
                        logger.info(
                            "%s [BARGE-IN] consecutive_speech_frames=%d state=%s",
                            log_prefix,
                            barge_in_speech_frames,
                            session.state,
                        )
                        barge_in_confirmed = True
                        await agent._cancel_tts(
                            websocket,
                            send_stop_audio=True,
                        )

                        session.set_state("listening")
                        barge_in_speech_frames = 0
                        # Wait until AudioManager has completed TTS cleanup
                        # and unmuted the STT provider.
                        if await _wait_for_stt_ready_after_barge_in():

                            if stt_send_buffer:
                                logger.info(
                                    "%s [BARGE-IN] Replaying %d buffered bytes to STT",
                                    log_prefix,
                                    len(stt_send_buffer),
                                )

                                await session.stt_provider.send_audio(
                                    bytes(stt_send_buffer)
                                )

                                stt_send_buffer.clear()

                                logger.info(
                                    "%s [BARGE-IN] Buffered audio replay complete",
                                    log_prefix,
                                )
                    
                    # Maximum segment duration: flush audio, but do NOT end the STT turn.
                    if "max_utterance" in events:
                        logger.info(
                            "%s [VAD] Maximum segment reached; flushing audio without "
                            "ending the STT turn",
                            log_prefix,
                        )

                        if stt_send_buffer and _stt_can_receive_audio():
                            if len(stt_send_buffer) < 1600:
                                stt_send_buffer.extend(
                                    b"\x00" * (1600 - len(stt_send_buffer))
                                )

                            await session.stt_provider.send_audio(bytes(stt_send_buffer))
                            stt_send_buffer.clear()
                    
                    # Genuine speech end: flush audio and finalize the STT turn.
                    if "speech_ended" in events:
                        # Discard speech only if it was NOT a confirmed barge-in.
                        if session.state == "speaking" and not barge_in_confirmed:
                            logger.debug(
                                "%s [VAD] Speech ended while assistant speaking; "
                                "discarding unconfirmed audio",
                                log_prefix,
                            )

                            stt_send_buffer.clear()
                            endpoint_speech_frames = 0
                            continue

                        
                        speech_end_time = time.perf_counter()
                        session.speech_end_time = speech_end_time

                        logger.info(
                            "%s [VAD] Speech ended",
                            log_prefix,
                        )

                        speech_frames_in_turn = endpoint_speech_frames
                        endpoint_speech_frames = 0

                        # Reset only after the utterance has ended.
                        barge_in_confirmed = False

                        if speech_frames_in_turn < MIN_ENDPOINT_SPEECH_FRAMES:
                            logger.debug(
                                "%s [VAD] Speech too short for ForceEndpoint: %d frames",
                                log_prefix,
                                speech_frames_in_turn,
                            )
                            continue

                        # Queue the timestamp BEFORE any further await.
                        # AssemblyAI may already have delivered its final
                        # transcript while local VAD was detecting silence.
                        pending_speech_end_times.append(speech_end_time)

                        logger.debug(
                            "%s [VAD] Queued speech-end timestamp. "
                            "Pending timestamps=%d | Pending transcripts=%d",
                            log_prefix,
                            len(pending_speech_end_times),
                            len(pending_final_transcripts),
                        )

                        # If AssemblyAI's final transcript arrived early,
                        # pair it with this timestamp now.
                        _dispatch_paired_transcripts()

                        # Make sure STT is ready before sending buffered audio.
                        if not _stt_can_receive_audio():
                            logger.info(
                                "%s [STT] Waiting for provider to become ready "
                                "before flushing buffered speech",
                                log_prefix,
                            )

                            if not await _wait_for_stt_ready_after_barge_in():
                                logger.warning(
                                    "%s [STT] Provider not ready; retaining buffered audio",
                                    log_prefix,
                                )
                                continue

                        # Flush the remaining speech audio.
                        if stt_send_buffer:
                            if len(stt_send_buffer) < 1600:
                                stt_send_buffer.extend(
                                    b"\x00" * (1600 - len(stt_send_buffer))
                                )

                            logger.info(
                                "%s [STT] Sending final buffered audio: %d bytes",
                                log_prefix,
                                len(stt_send_buffer),
                            )

                            await session.stt_provider.send_audio(
                                bytes(stt_send_buffer)
                            )

                            stt_send_buffer.clear()

                        logger.info(
                            "%s Sending ForceEndpoint to STT",
                            log_prefix,
                        )

                        task = asyncio.create_task(_force_end_turn())
                        endpoint_tasks.add(task)
                        task.add_done_callback(endpoint_tasks.discard)
                    
            except Exception as e:
                logger.exception(
                    "%s Audio processing failed ",
                    log_prefix
                )
                if isinstance(e, STTConnectionError) and conversation_started:
                    asyncio.create_task(_reconnect_stt())

        # Main loop 
        try:
            while True:
                message = await websocket.receive()
                # if "bytes" in message:
                #     logger.info(f"Received audio from browser: {len(message['bytes'])} bytes")

                if message["type"] == "websocket.disconnect":
                    break

                if "bytes" in message:
                    pcm_bytes = message["bytes"]  # This is pcm from browser
                    #Only after greeting and stt start will stt_accepting be set to true
                    if stt_accepting:
                        await send_audio_to_stt(pcm_bytes)
                    #User clicks start ,greeting plays and starts speaking.STT still connecting 
                    elif conversation_started:
                        early_audio_buffer.append(pcm_bytes)
                    # User hasnt pressed start
                    continue
                
                # Text data sent from frontend
                if "text" in message:
                    try:
                        data = json.loads(message["text"])
                    except Exception:
                        continue
                else:
                    continue
                # User clicks start.Prevents the user from starting the session twice.
                if data.get("type") == "start" and not conversation_started:
                    conversation_started = True
                    try:
                        # Send a greeting_started message to the frontend to indicate that the greeting is about to be played
                        await websocket.send_json({"type": "greeting_started"})
                    except Exception as e:
                        raise WebSocketError(f"Failed to send greeting_started: {e}") from e
                    # If greeting message is set
                    if greeting_message:
                        # Send the greeting message to the frontend for display
                        await websocket.send_json({
                            "type": "transcript",
                            "speaker": "assistant",
                            "text": greeting_message
                        })
                        # Flag to prevent greeting from being interrupted by speaker echo or tts leakage
                        session.ignore_barge_in_once = True
                        try:
                            await audio_manager.stream_text(
                                websocket,
                                greeting_message,
                                session
                            )
                        except TTSError as e:
                            logger.error(
                                "%s [Router] Greeting TTS failed: %s",
                                log_prefix,
                                e,
                            )

                            if (
                                websocket.client_state == WebSocketState.CONNECTED
                                and websocket.application_state == WebSocketState.CONNECTED
                            ):
                                try:
                                    await websocket.send_json({
                                        "type": "tts_error",
                                        "message": (
                                            "Unable to play the greeting. "
                                            "You can still start speaking."
                                        ),
                                    })
                                except Exception:
                                    logger.warning(
                                        "%s [Router] Could not send greeting TTS error; "
                                        "the WebSocket may be closing.",
                                        log_prefix,
                                    )
                    try:
                        # Send a greeting_done message to the frontend to indicate that the greeting has finished playing
                        await websocket.send_json({"type": "greeting_done"})
                    except Exception as e:
                        raise WebSocketError(f"Failed to send greeting_done: {e}") from e
                    # Open websocket and connect to STT provider for streaming
                    session.stt_provider.start_streaming(
                        on_transcript=on_transcript,
                        on_error=on_error,
                    )
                    
                    logger.info(
                        "%s STT streaming started",
                        log_prefix,
                    )
                    
                    # Wait for STT provider to be ready before accepting audio
                    wait_attempts = 0
                    while not session.stt_provider.is_ready:
                        await asyncio.sleep(0.05)
                        wait_attempts += 1
                        # Timeout protection .05 * 300 = 15 secs
                        if wait_attempts > 300:
                            logger.error(
                                "%s STT never became ready",
                                log_prefix,
                            )
                            break
                    if not session.stt_provider.is_ready:
                        logger.error(
                            "%s [Router] STT connection failed. "
                            "Ending session startup.",
                            log_prefix,
                        )
                        break
                    # Previously stored user audio before the STT provider became ready
                    if early_audio_buffer:
                        logger.info(
                            "%s Replaying %d buffered audio chunks",
                            log_prefix,
                            len(early_audio_buffer),
                        )
                        # Replay the buffered audio to the STT provider now that it is ready
                        for buffered_bytes in early_audio_buffer:
                            await send_audio_to_stt(buffered_bytes)
                        early_audio_buffer.clear()
                        logger.info(
                            "%s Early audio replay complete",
                            log_prefix,
                        )
                    # Set the flag to start accepting audio for STT and update session state
                    stt_accepting = True
                    session.set_state("listening")
                    logger.info(
                        "%s STT provider ready",
                        log_prefix,
                    )

                    try:
                        # Send a listening_ready message to the frontend to indicate that the system is ready to accept user input
                        await websocket.send_json({"type": "listening_ready"})
                    except Exception as e:
                        raise WebSocketError(f"Failed to send listening_ready: {e}") from e
                
                # User clicks stop. Stops the session and cleans up resources.
                elif data.get("type") == "stop":
                    logger.info(
                        "%s Stop requested by frontend",
                        log_prefix,
                    )
                    _log_and_reset_barge_in_rms("session_stopped")
                    stt_accepting = False
                    vad_manager.reset()
                    vad_buffer.clear()
                    stt_send_buffer.clear()
                    pending_speech_end_times.clear()
                    pending_final_transcripts.clear()
                    session.stt_provider.stop_streaming()
                    break
                
                # User interrupts the assistant while it is speaking. Stops TTS and resets VAD and buffers.
                # elif data.get("type") == "interrupt":
                #     logger.info(
                #         "%s [BARGE-IN] Interrupt received",
                #         log_prefix,
                #     )
                #     await agent._cancel_tts(websocket, send_stop_audio=True)
                #     vad_manager.reset()
                #     vad_buffer.clear()
                #     stt_send_buffer.clear()
                #     session.set_state("listening")
                    
                #     # This handles cases where STT websocket closed during interrupt.
                #     if not session.stt_provider.is_listening or not session.stt_provider.is_ready:
                #         session.stt_provider.start_streaming(
                #             on_transcript=on_transcript,
                #             on_error=on_error,
                #         )
                #         # Timeout of 3 seconds for STT to be ready after an interrupt
                #         for _ in range(60):
                #             if session.stt_provider.is_ready:
                #                 break
                #             await asyncio.sleep(0.05)

        except WebSocketDisconnect:
            logger.info(
                "%s WebSocket disconnected",
                log_prefix,
            )

        finally:
            logger.info(
                "%s Cleaning up session resources",
                log_prefix,
            )
            _log_and_reset_barge_in_rms("session_cleanup")
            stt_accepting = False
            # Cancel any normal-response TTS task before closing the WebSocket.
            # Do not try to send clear_audio during cleanup.
            try:
                await agent._cancel_tts(
                    websocket,
                    send_stop_audio=False,
                )
            except Exception:
                logger.exception(
                    "%s Failed to cancel TTS during cleanup",
                    log_prefix,
                )
            
            # Cancel and await outstanding endpoint tasks.
            if endpoint_tasks:
                logger.info(
                    "%s Cancelling %d pending endpoint tasks",
                    log_prefix,
                    len(endpoint_tasks),
                )

                for task in endpoint_tasks:
                    task.cancel()

                await asyncio.gather(
                    *endpoint_tasks,
                    return_exceptions=True,
                )

                endpoint_tasks.clear()
            vad_manager.reset()
            vad_buffer.clear()
            stt_send_buffer.clear()
            pending_speech_end_times.clear()
            pending_final_transcripts.clear()
            if session.stt_provider and session.stt_provider.is_listening():
                session.stt_provider.stop_streaming()
            session.reset_session()
            if websocket.client_state != WebSocketState.DISCONNECTED:
                await websocket.close()

    return router


