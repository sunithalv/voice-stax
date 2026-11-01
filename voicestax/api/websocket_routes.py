# WebSocket routes for the voice assistant.
# This file manages real-time chat connections, initializes speech and language providers,
# streams audio/text between the client and the agent, and maintains session state.

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
import asyncio
import json
import time
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
from voicestax.utils.exceptions import ProviderInitializationError, WebSocketError, WebSocketConnectionError,TTSError
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
                
        async def _process_final_transcript(text: str) -> None:
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
            await _handle_message(text)


        def on_transcript(text: str, is_final: bool) -> None:
            """Receive transcript callbacks from the STT provider."""

            if not text or not is_final:
                return

            session.stt_final_time = time.perf_counter()
            
            logger.info(
                "%s [STT] Final transcript received: %s",
                session.log_prefix(),
                text,
            )

            asyncio.create_task(
                _process_final_transcript(text)
            )
        
        # Callback for handling errors from the STT provider
        def on_error(e: Exception):
            asyncio.create_task(send_error_message(str(e)))

        # Helper function to handle user messages, send them to the agent, and manage session state
        async def _handle_message(text: str):
            nonlocal stt_accepting, conversation_started
            logger.info(
                "%s User message received: %s",
                log_prefix,
                text,
            )
            if session.speech_end_time:
                # Calculate STT latency in milliseconds
                stt_latency = (
                    session.stt_final_time - session.speech_end_time
                ) * 1000

                session.record_latency(
                    "stt_latency",
                    round(stt_latency, 2)
                )
                
                logger.info(
                    "%s [STT] Final transcript received: %s | latency=%.2f ms",
                    session.log_prefix(),
                    text,
                    stt_latency,
                )

            await agent.handle_user_message(text, websocket)

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
            logger.info(
                "%s LATENCY | STT=%.2fms | LLM=%.2fms | "
                "TTS=%.2fms | TOTAL=%.2fms",
                log_prefix,
                session.latency_metrics.get("stt_latency", 0),
                session.latency_metrics.get("llm_latency", 0),
                session.latency_metrics.get("tts_latency", 0),
                session.latency_metrics.get("total_turn_latency", 0),
            )

        # Process incoming PCM audio through VAD, stream detected speech
        # frames to STT in batches, handle speech state transitions and
        # barge-in, and finalize the STT turn when the utterance ends.
        barge_in_speech_frames = 0
        # Speech frames seen since the last ForceEndpoint. Short bursts
        # (coughs, clicks, speaker echo) should not finalize the STT turn,
        # otherwise real sentences get chopped into fragments like "Oh."
        endpoint_speech_frames = 0
        MIN_ENDPOINT_SPEECH_FRAMES = 10  # 200 ms at 20 ms frames
        # Strong references so background endpoint tasks aren't garbage-collected.
        endpoint_tasks: set[asyncio.Task] = set()
        
        force_endpoint_in_progress = False

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

        async def send_audio_to_stt(pcm_bytes: bytes):
            nonlocal barge_in_speech_frames, endpoint_speech_frames
            try:
                
                # Process through VAD
                vad_buffer.extend(pcm_bytes)
                logger.debug(f"PCM chunk size: {len(pcm_bytes)}")
                
                while len(vad_buffer) >= FRAME_SIZE:
                    frame = bytes(vad_buffer[:FRAME_SIZE])
                    del vad_buffer[:FRAME_SIZE]

                    is_speech = vad.is_speech(frame)

                    events = vad_manager.process_frame(is_speech)

                    logger.debug(
                        "%s VAD frame classified as %s",
                        log_prefix,
                        "speech" if is_speech else "silence",
                    )

                    # Buffer speech audio for STT.
                    if is_speech:
                        endpoint_speech_frames += 1
                        stt_send_buffer.extend(frame)

                        if len(stt_send_buffer) >= 3200:
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
                    
                    if session.state == "speaking" and session.is_speaking:
                        logger.debug(
                            "%s [BARGE-IN DEBUG] is_speech=%s consecutive_frames=%d",
                            log_prefix,
                            is_speech,
                            barge_in_speech_frames,
                        )
                    # Require sustained speech before interrupting TTS.
                    # For 20 ms VAD frames, 15 frames = 300 ms.
                    if (
                        session.state == "speaking"
                        and session.is_speaking
                        and barge_in_speech_frames >= 15
                    ):
                        logger.info(
                            "%s [BARGE-IN] consecutive_speech_frames=%d state=%s",
                            log_prefix,
                            barge_in_speech_frames,
                            session.state,
                        )

                        await agent._cancel_tts(
                            websocket,
                            send_stop_audio=True,
                        )

                        session.set_state("listening")
                        barge_in_speech_frames = 0
                        # Do not reset vad_manager here.
                        # Continue tracking this same user utterance.
                    
                    # Maximum segment duration: flush audio, but do NOT end the STT turn.
                    if "max_utterance" in events:
                        logger.info(
                            "%s [VAD] Maximum segment reached; flushing audio without "
                            "ending the STT turn",
                            log_prefix,
                        )

                        if stt_send_buffer:
                            if len(stt_send_buffer) < 1600:
                                stt_send_buffer.extend(
                                    b"\x00" * (1600 - len(stt_send_buffer))
                                )

                            await session.stt_provider.send_audio(bytes(stt_send_buffer))
                            stt_send_buffer.clear()
                    
                    # Genuine speech end: flush audio and finalize the STT turn.
                    if "speech_ended" in events:
                        session.speech_end_time = time.perf_counter()

                        logger.info("%s [VAD] Speech ended", log_prefix)

                        if stt_send_buffer:
                            if len(stt_send_buffer) < 1600:
                                stt_send_buffer.extend(
                                    b"\x00" * (1600 - len(stt_send_buffer))
                                )

                            logger.info(
                                "%s Flushing %d bytes to STT",
                                log_prefix,
                                len(stt_send_buffer),
                            )

                            await session.stt_provider.send_audio(bytes(stt_send_buffer))
                            stt_send_buffer.clear()

                        speech_frames_in_turn = endpoint_speech_frames
                        endpoint_speech_frames = 0

                        if speech_frames_in_turn < MIN_ENDPOINT_SPEECH_FRAMES:
                            logger.debug(
                                "%s Skipping ForceEndpoint for short speech burst (%d frames)",
                                log_prefix,
                                speech_frames_in_turn,
                            )
                            continue

                        logger.info("%s Sending ForceEndpoint to STT", log_prefix)

                        task = asyncio.create_task(_force_end_turn())
                        endpoint_tasks.add(task)
                        task.add_done_callback(endpoint_tasks.discard)
                    
            except Exception as e:
                logger.exception(
                    "%s Audio processing failed ",
                    log_prefix
                )

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
                    stt_accepting = False
                    vad_manager.reset()
                    vad_buffer.clear()
                    stt_send_buffer.clear()
                    session.stt_provider.stop_streaming()
                    break
                
                # User interrupts the assistant while it is speaking. Stops TTS and resets VAD and buffers.
                elif data.get("type") == "interrupt":
                    logger.info(
                        "%s [BARGE-IN] Interrupt received",
                        log_prefix,
                    )
                    await agent._cancel_tts(websocket, send_stop_audio=True)
                    vad_manager.reset()
                    vad_buffer.clear()
                    stt_send_buffer.clear()
                    session.set_state("listening")
                    
                    # This handles cases where STT websocket closed during interrupt.
                    if not session.stt_provider.is_listening or not session.stt_provider.is_ready:
                        session.stt_provider.start_streaming(
                            on_transcript=on_transcript,
                            on_error=on_error,
                        )
                        # Timeout of 3 seconds for STT to be ready after an interrupt
                        for _ in range(60):
                            if session.stt_provider.is_ready:
                                break
                            await asyncio.sleep(0.05)

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
            if session.stt_provider and session.stt_provider.is_listening:
                session.stt_provider.stop_streaming()
            session.reset_session()
            if websocket.client_state != WebSocketState.DISCONNECTED:
                await websocket.close()

    return router


