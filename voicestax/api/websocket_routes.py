from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
import asyncio
import base64
import json

from voicestax.session.voice_session import SessionData
from voicestax.core.voice_agent import VoiceAgent
from voicestax.core.chat_engine import ChatEngine
from voicestax.core.audio_manager import AudioManager
from voicestax.config.settings import VoiceSettings  
from voicestax.providers.stt.factory import get_stt_provider
from voicestax.providers.tts.factory import get_tts_provider
from voicestax.providers.llm.factory import get_llm_provider
from voicestax.utils.exceptions import ProviderInitializationError, WebSocketError, WebSocketConnectionError
from voicestax.utils.logger import logger


def create_router(settings: VoiceSettings) -> APIRouter:
    """
    Returns a configured APIRouter with the given settings baked in.
    Called once by create_voice_app() — settings are captured via closure.
    """
    router = APIRouter()

    @router.websocket("/ws/chat")
    async def websocket_endpoint(websocket: WebSocket):
        # `settings` is captured from the outer create_router() scope —
        # this is the closure that replaces the old module-level import

        try:
            await websocket.accept()
            logger.info("✅ WebSocket connected")
        except Exception as e:
            raise WebSocketConnectionError(f"Failed to establish WebSocket connection: {e}") from e

        session = SessionData()
        agent = None
        conversation_started = False

        first_speaker = settings.first_speaker or "assistant"
        greeting_message = (
            settings.initial_message if first_speaker == "assistant" else None
        )

        early_audio_buffer = []
        stt_accepting = False

        try:
            stt_provider = get_stt_provider(
                provider_name=settings.stt_provider,
                api_key=settings.get_api_key("stt"),
                sample_rate=settings.stt_sample_rate,
                encoding=settings.stt_encoding,
                model=settings.stt_model,
            )

            llm_provider = get_llm_provider(
                provider_name=settings.llm_provider,
                api_key=settings.get_api_key("llm"),
                model=settings.llm_model,
                max_tokens=settings.llm_max_tokens,
            )

            tts_provider = get_tts_provider(
                provider_name=settings.tts_provider,
                api_key=settings.get_api_key("tts"),
                voice_id=settings.tts_voice_id,
                model_id=settings.tts_model,
                output_format=settings.tts_output_format,
                optimize_latency=settings.tts_optimize_latency,
            )

            session.stt_provider = stt_provider
            session.llm_provider = llm_provider

            audio_manager = AudioManager(
                tts_client=tts_provider,
                sample_rate=settings.tts_sample_rate,
            )

            session.tts_provider = audio_manager
            session.voice_id = settings.tts_voice_id
            session.system_prompt = settings.llm_system_prompt

            agent = VoiceAgent(
                session=session,
                audio_manager=audio_manager,
                chat_engine=ChatEngine(llm_provider),
                settings=settings,   # pass through so VoiceAgent doesn't re-read .env
            )

            try:
                await websocket.send_json({"type": "system_ready"})
            except Exception as e:
                raise WebSocketError(f"Failed to send system_ready: {e}") from e

        except Exception as e:
            logger.error(f"❌ Initialization error: {e}")
            raise ProviderInitializationError(f"Failed to initialize providers: {e}") from e

        # ── STT callbacks ────────────────────────────────────────────────────
        async def send_transcription(text: str):
            try:
                await websocket.send_json({"type": "transcription", "text": text})
            except Exception as e:
                logger.error(f"WebSocket error sending transcription: {e}")

        async def send_error_message(message: str):
            try:
                await websocket.send_json({"type": "error", "message": message})
            except Exception as e:
                logger.error(f"WebSocket error sending error message: {e}")

        def on_transcript(text: str, is_final: bool):
            if text and is_final:
                asyncio.create_task(send_transcription(text))
                asyncio.create_task(_handle_message(text))

        def on_error(e: Exception):
            asyncio.create_task(send_error_message(str(e)))

        async def _handle_message(text: str):
            nonlocal stt_accepting, conversation_started

            await agent.handle_user_message(text, websocket)

            if getattr(session, "ended", False) or getattr(agent, "session_ended", False):
                stt_accepting = False
                conversation_started = False
                try:
                    session.stt_provider.stop_streaming()
                except Exception as e:
                    logger.warning(f"⚠️ STT stop error: {e}")

                session.reset_session()

                if hasattr(session, "ended"):
                    session.ended = False
                if hasattr(agent, "session_ended"):
                    agent.session_ended = False

                try:
                    await websocket.send_json({"type": "session_ended"})
                except Exception as e:
                    raise WebSocketError(f"Failed to send session_ended: {e}") from e

        async def send_audio_to_stt(audio_bytes: bytes):
            try:
                await session.stt_provider.send_audio(audio_bytes)
            except Exception as e:
                logger.warning(f"⚠️ Audio send failed: {e}")

        # ── Main loop ────────────────────────────────────────────────────────
        try:
            while True:
                message = await websocket.receive()

                if message["type"] == "websocket.disconnect":
                    break

                if "bytes" in message:
                    audio_bytes = message["bytes"]
                    if stt_accepting:
                        await send_audio_to_stt(audio_bytes)
                    elif conversation_started:
                        early_audio_buffer.append(audio_bytes)
                    continue

                if "text" in message:
                    try:
                        data = json.loads(message["text"])
                    except Exception:
                        continue
                else:
                    continue

                if data.get("type") == "start" and not conversation_started:
                    conversation_started = True
                    try:
                        await websocket.send_json({"type": "greeting_started"})
                    except Exception as e:
                        raise WebSocketError(f"Failed to send greeting_started: {e}") from e

                    if greeting_message:
                        await audio_manager.stream_text(websocket, greeting_message, session)

                    try:
                        await websocket.send_json({"type": "greeting_done"})
                    except Exception as e:
                        raise WebSocketError(f"Failed to send greeting_done: {e}") from e

                    session.stt_provider.start_streaming(
                        on_transcript=on_transcript,
                        on_error=on_error,
                    )

                    wait_attempts = 0
                    while not session.stt_provider.is_ready:
                        await asyncio.sleep(0.05)
                        wait_attempts += 1
                        if wait_attempts > 100:
                            logger.error("❌ STT never became ready")
                            break

                    stt_accepting = True

                    if early_audio_buffer:
                        for buffered_bytes in early_audio_buffer:
                            await send_audio_to_stt(buffered_bytes)
                        early_audio_buffer.clear()

                    stt_accepting = True
                    session.set_state("listening")
                    try:
                        await websocket.send_json({"type": "listening_ready"})
                    except Exception as e:
                        raise WebSocketError(f"Failed to send listening_ready: {e}") from e

                elif data.get("type") == "stop":
                    stt_accepting = False
                    session.stt_provider.stop_streaming()
                    break

                elif data.get("type") == "audio":
                    if not stt_accepting:
                        continue
                    audio_bytes = base64.b64decode(data["data"])
                    await send_audio_to_stt(audio_bytes)

                elif data.get("type") == "interrupt":
                    await agent._cancel_tts(websocket, send_stop_audio=False)
                    await session.stt_provider.force_end_turn(fallback_callback=on_transcript)

                    if not session.stt_provider._is_listening or not session.stt_provider.is_ready:
                        session.stt_provider.start_streaming(
                            on_transcript=on_transcript,
                            on_error=on_error,
                        )
                        for _ in range(60):
                            if session.stt_provider.is_ready:
                                break
                            await asyncio.sleep(0.05)

        except WebSocketDisconnect:
            logger.info("❌ WebSocket disconnected")

        finally:
            stt_accepting = False
            if session.stt_provider:
                session.stt_provider.stop_streaming()
            session.reset_session()
            if websocket.client_state != WebSocketState.DISCONNECTED:
                await websocket.close()

    return router