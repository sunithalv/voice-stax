# Runtime session state for a live voice assistant.
# This module defines SessionData to track providers, conversation state,
# barge-in behavior, and latency during an active voice session.

import asyncio
import uuid
import time
from typing import Optional,Any
from fastapi import WebSocket

from voicestax.providers.llm.base import BaseLLMProvider
from voicestax.providers.tts.base import BaseTTSProvider
from voicestax.providers.stt.base import BaseSTTProvider
from voicestax.utils.exceptions import SessionStateError
from voicestax.config.settings import VoiceSettings
from voicestax.utils.logger import logger


class SessionData:
    """
    Holds runtime state for a single voice session.
    """

    # Initialization of the session state
    def __init__(self,settings:VoiceSettings):
        # Unique session identifier
        self.session_id: str = str(uuid.uuid4())
        
        # Save the settings for the session
        self.settings=settings

        # Provider references (injected externally)
        self.llm_provider: Optional[BaseLLMProvider] = None
        self.tts_provider: Optional[BaseTTSProvider] = None
        self.stt_provider: Optional[BaseSTTProvider] = None

        # Conversation history for the session (user and assistant messages)
        self.conversation_history: list[dict[str, Any]] = []

        # -------------------------------
        # State machine
        # -------------------------------
        # idle → listening → processing → speaking
        self.state: str = "idle"

        # Assistant speaking or TTS playback in progress.
        self.is_speaking: bool = False
        #prevents old audio from overlapping with new user input.
        self.current_response_id: int = 0

        # -------------------------------
        # Barge-in control
        # -------------------------------
        
        self.was_interrupted = False
        #Prevent accidental interruption
        self.ignore_barge_in_once: bool = False
        #most recent finalized user transcript
        self.last_user_text: Optional[str] = None

        # -------------------------------
        # Concurrency & cancellation
        # -------------------------------
        #prevent concurrent LLM processing for the same session.
        self.processing_lock: asyncio.Lock = asyncio.Lock()
        #cancel the current assistant response pipeline
        self.cancel_event: asyncio.Event = asyncio.Event()
        # Tracks ownership of STT mute/unmute across overlapping TTS tasks.
        self.tts_generation: int = 0

        # -------------------------------
        # Timing & analytics
        # -------------------------------
        self.session_start_time: float = time.time()
        self.last_activity_time: float = time.time()

        # Latency metrics for each stage of the voice session pipeline.
        self.latency_metrics: dict[str, float] = {}
        # Metrics for the currently handled user turn. Welcome audio has no record.
        self.current_turn_latency: Optional[dict[str, float]] = None
        self.turn_count: int = 0
        self.language: str = "en"
        
        # Timing markers
        # User speech end time 
        self.speech_end_time: float = 0.0
        # Final STT transcript time 
        self.stt_final_time: float = 0.0
        
        # LLM processing start and end times
        self.llm_start_time: float = 0.0
        self.llm_end_time: float = 0.0
        
        # TTS start time and first chunk time 
        self.tts_start_time: float = 0.0
        self.tts_first_chunk_time: float = 0.0

    # Session state management methods
    def set_state(self, new_state: str):
        valid_states = {"idle", "listening", "processing", "speaking"}

        if new_state not in valid_states:
            raise SessionStateError(
                f"Invalid session state: {new_state}. "
                f"Valid states: {valid_states}"
            )

        old_state = self.state
        self.state = new_state
        self.last_activity_time = time.time()
        
        logger.info(
            f"[Session {self.session_id}] [STATE] "
            f"{old_state} -> {new_state}"
        )
    
    # Increment the response ID to invalidate previous streams, useful for barge-in handling.
    def increment_response_id(self):
        """
        Used for barge-in handling.
        Increments response ID to invalidate previous streams.
        """
        self.current_response_id += 1
    
    # Get the duration of the session in seconds.     
    def get_session_duration(self) -> float:
        return time.time() - self.session_start_time
    
    # Barge-in handling methods
    def trigger_barge_in(self):
        """
        Stops current speaking stream safely.
        """
        self.was_interrupted = True
        self.is_speaking = False
        self.increment_response_id()
        self.cancel_event.set()
    
    # Record latency metrics for each stage of the voice session pipeline.
    def record_latency(self, key: str, value: float):
        """
        Store latency metric.
        """
        if self.current_turn_latency is not None:
            self.current_turn_latency[key] = value
        self.latency_metrics[key] = value

    def start_turn_latency(self, speech_end_time: float, stt_final_time: float) -> None:
        """Start an isolated latency record for one finalized user turn."""
        # Keep the turn's speech boundary with its metrics. VAD continues
        # updating the session-level marker while assistant audio is playing.
        self.current_turn_latency = {"_speech_end_time": speech_end_time}
        self.latency_metrics = self.current_turn_latency
        self.speech_end_time = speech_end_time
        self.stt_final_time = stt_final_time
        self.record_latency(
            "stt_latency",
            round((stt_final_time - speech_end_time) * 1000, 2),
        )

    def finish_turn_latency(self) -> dict[str, float]:
        """Close and return the current turn record."""
        metrics = self.current_turn_latency or {}
        self.current_turn_latency = None
        return metrics
    
    # Logging helper to prefix log messages with the session ID.
    def log_prefix(self) -> str:
        return f"[Session {self.session_id}]"

    # Reset transient session state while keeping provider references intact.
    def reset_session(self):
        logger.info(
            "%s Session reset",
            self.log_prefix(),
        )
        self.state = "idle"
        self.is_speaking = False
        #self.current_response_id = 0

        self.was_interrupted = False
        self.ignore_barge_in_once = False
        self.last_user_text = None

        self.cancel_event.clear()

        self.last_activity_time = time.time()
        self.latency_metrics.clear()
        self.current_turn_latency = None
        self.turn_count = 0
        self.speech_end_time = 0.0
        self.stt_final_time = 0.0
        self.llm_start_time = 0.0
        self.llm_end_time = 0.0
        self.tts_start_time = 0.0
        self.tts_first_chunk_time = 0.0
        self.conversation_history.clear()
