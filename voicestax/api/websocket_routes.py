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
        logger.info("%s Session started", session.log_prefix())

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
                **settings.stt_config
            )
            logger.info("%s STT initialized", session.log_prefix())

            llm_provider = custom_llm_provider or get_llm_provider(
                provider_name=settings.llm_provider,
                api_key=settings.get_api_key("llm"),
                **settings.llm_config,
            )
            logger.info("%s LLM initialized", session.log_prefix())
            
            tts_provider = get_tts_provider(
                provider_name=settings.tts_provider,
                api_key=settings.get_api_key("tts"),
                **settings.tts_config,
            )
            logger.info("%s TTS initialized", session.log_prefix())
 
            # Add the providers to the session for later use
            session.stt_provider = stt_provider
            session.llm_provider = llm_provider

            audio_manager = AudioManager(
                tts_client=tts_provider,
                stt_client=stt_provider
            )
            logger.info("%s Audio manager initialized", session.log_prefix())
            
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
                session.log_prefix(),
            )

            # Initialize VAD
            vad = get_vad_provider(
                provider_name=settings.vad_provider,
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
                session.log_prefix(),
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
        # Callback for handling transcripts from the STT provider
        def on_transcript(text: str, is_final: bool):
            if text and is_final:
                # Record the time when the final transcript is received from STT provider
                session.stt_final_time = time.perf_counter()
                asyncio.create_task(send_transcription(text))
                asyncio.create_task(_handle_message(text))
        
        # Callback for handling errors from the STT provider
        def on_error(e: Exception):
            asyncio.create_task(send_error_message(str(e)))

        # Helper function to handle user messages, send them to the agent, and manage session state
        async def _handle_message(text: str):
            nonlocal stt_accepting, conversation_started
            logger.info(
                "%s User message received: %s",
                session.log_prefix(),
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

            await agent.handle_user_message(text, websocket)

            if agent.session_ended:
                logger.info(
                    "%s Session end detected - cleaning up",
                    session.log_prefix(),
                )
                stt_accepting = False
                conversation_started = False
                agent.reset_session_ended()
                try:
                    session.stt_provider.stop_streaming()
                except Exception as e:
                    logger.warning(
                        "%s STT stop error: %s",
                        session.log_prefix(),
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
                session.log_prefix(),
                session.latency_metrics.get("stt_latency", 0),
                session.latency_metrics.get("llm_latency", 0),
                session.latency_metrics.get("tts_latency", 0),
                session.latency_metrics.get("total_turn_latency", 0),
            )

        # Process incoming PCM audio through VAD, stream detected speech
        # frames to STT in batches, handle speech state transitions and
        # barge-in, and finalize the STT turn when the utterance ends.
        async def send_audio_to_stt(pcm_bytes: bytes):
            try:
                
                # Process through VAD
                vad_buffer.extend(pcm_bytes)
                logger.debug(f"PCM chunk size: {len(pcm_bytes)}")
                
                while len(vad_buffer) >= FRAME_SIZE:
                    # Extract a frame for VAD processing based on the calculated FRAME_SIZE
                    frame = bytes(vad_buffer[:FRAME_SIZE])

                    del vad_buffer[:FRAME_SIZE]
                    
                    # Classify audio frame as speech or non-speech using the VAD provider.
                    is_speech = vad.is_speech(frame)
                    
                    logger.debug(
                        "%s VAD frame classified as %s",
                        session.log_prefix(),
                        "speech" if is_speech else "silence",
                    )

                    events = vad_manager.process_frame(
                        is_speech
                    )

                    #Only speech frames will be sent to STT
                    if is_speech:
                        stt_send_buffer.extend(frame)

                        #Each frame in PCM 16 for 20ms duration and 16Hz sample rate at 2 bytes per frame is (2*.02*16000) = 640 bytes.
                        #So we can send to STT in batches of 5 frames ie 3200 bytes for better performance.
                        if len(stt_send_buffer) >= 3200:
                            logger.debug(
                                "%s Sending %d bytes to STT",
                                session.log_prefix(),
                                len(stt_send_buffer),
                            )
                            await session.stt_provider.send_audio(
                                bytes(stt_send_buffer)
                            )

                            stt_send_buffer.clear()

                    if "speech_started" in events:
                        
                        logger.info(
                            "%s [VAD] Speech started "
                            "state=%s speech_frames=%d",
                            session.log_prefix(),
                            session.state,
                            vad_manager.speech_frames,
                        )

                        # Actual Barge In logic  handled here
                        if (
                            is_speech
                            and session.state == "speaking"
                            and session.is_speaking 
                            and vad_manager.speech_frames >= 10
                        ):

                            logger.info(
                                "%s [BARGE-IN] "
                                "speech_frames=%d state=%s",
                                session.log_prefix(),
                                vad_manager.speech_frames,
                                session.state,
                            )

                            await agent._cancel_tts(
                                websocket,
                                send_stop_audio=True
                            )
                            vad_manager.reset()
                            #vad_buffer.clear()
                            #stt_send_buffer.clear()

                            session.set_state("listening")

                    if "speech_ended" in events  or "max_utterance" in events:                        
                        # Record time VAD determined the user stopped speaking
                        session.speech_end_time = time.perf_counter()
                        reason = (
                            "Speech ended"
                            if "speech_ended" in events
                            else "Max utterance reached"
                        )

                        logger.info(
                            "%s [VAD] %s",
                            session.log_prefix(),
                            reason,
                        )
                        #Assemblyai required minimum 50ms and max 1000ms audio to process.
                        #For 16kHz PCM16: 50ms will be (0.05 * 16000 * 2) = 1600 bytes.
                        if stt_send_buffer:
                            #to avoid loss of audio, we can pad the buffer with zeros to make it 1600 bytes if it's less than that.
                            if len(stt_send_buffer) < 1600:
                                padding = b"\x00" * (1600 - len(stt_send_buffer))
                                stt_send_buffer.extend(padding)

                            logger.info(
                                "%s Flushing %d bytes to STT",
                                session.log_prefix(),
                                len(stt_send_buffer),
                            )
                            # If speech ended send remaining audio in buffer to STT
                            await session.stt_provider.send_audio(
                                bytes(stt_send_buffer)
                            )

                            stt_send_buffer.clear()
                        
                        # force_end_turn is the signal that speech has ended and the transcript can be finalized by the stt.
                        logger.info(
                            "%s Sending ForceEndpoint to STT",
                            session.log_prefix(),
                        )
                        await session.stt_provider.force_end_turn(
                            fallback_callback=on_transcript
                        )
                    
            except Exception as e:
                logger.exception(
                    "%s Audio processing failed ",
                    session.log_prefix()
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
                                session.log_prefix(),
                                e,
                            )

                            await websocket.send_json({
                                "type": "tts_error",
                                "message": "Unable to play the greeting. You can still start speaking.",
                            })
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
                        session.log_prefix(),
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
                                session.log_prefix(),
                            )
                            break
                    # Previously stored user audio before the STT provider became ready
                    if early_audio_buffer:
                        logger.info(
                            "%s Replaying %d buffered audio chunks",
                            session.log_prefix(),
                            len(early_audio_buffer),
                        )
                        # Replay the buffered audio to the STT provider now that it is ready
                        for buffered_bytes in early_audio_buffer:
                            await send_audio_to_stt(buffered_bytes)
                        early_audio_buffer.clear()
                        logger.info(
                            "%s Early audio replay complete",
                            session.log_prefix(),
                        )
                    # Set the flag to start accepting audio for STT and update session state
                    stt_accepting = True
                    session.set_state("listening")
                    logger.info(
                        "%s STT provider ready",
                        session.log_prefix(),
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
                        session.log_prefix(),
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
                        session.log_prefix(),
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
                session.log_prefix(),
            )

        finally:
            logger.info(
                "%s Cleaning up session resources",
                session.log_prefix(),
            )
            stt_accepting = False
            vad_manager.reset()
            vad_buffer.clear()
            stt_send_buffer.clear()
            if session.stt_provider and session.stt_provider.is_listening:
                session.stt_provider.stop_streaming()
            session.reset_session()
            if websocket.client_state != WebSocketState.DISCONNECTED:
                await websocket.close()

    return router


