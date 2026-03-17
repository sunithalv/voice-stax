"""
SessionData: Runtime state container for a voice session.

Responsibilities:
- Manage session lifecycle
- Track streaming state
- Handle barge-in & cancellation
- Maintain latency metrics
- Store provider references
"""

import asyncio
import uuid
import time
from typing import Optional
from fastapi import WebSocket

from voicestax.providers.llm.base import BaseLLMProvider
from voicestax.providers.tts.base import BaseTTSProvider
from voicestax.providers.stt.base import BaseSTTProvider
from voicestax.utils.exceptions import SessionStateError


class SessionData:
    """
    Holds runtime state for a single voice session.
    """

    # -------------------------------
    # Initialization
    # -------------------------------

    def __init__(self):
        # Unique session identifier
        self.session_id: str = str(uuid.uuid4())

        # Provider references (injected externally)
        self.llm_provider: Optional[BaseLLMProvider] = None
        self.tts_provider: Optional[BaseTTSProvider] = None
        self.stt_provider: Optional[BaseSTTProvider] = None

        # Voice configuration
        self.voice_id: str = ""
        
        #LLM system prompt (can be customized per session)
        self.system_prompt: Optional[str] = None

        # Active WebSocket
        self.current_websocket: Optional[WebSocket] = None

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
        # Timestamp of last finalized STT transcript. Useful for advanced barge-in, duplicate detection, or analytics.
        # Currently unused.
        self.last_final_transcript_time: float = 0.0

        # -------------------------------
        # Concurrency & cancellation
        # -------------------------------
        #prevent concurrent LLM processing for the same session.
        self.processing_lock: asyncio.Lock = asyncio.Lock()
        #cancel the current assistant response pipeline
        self.cancel_event: asyncio.Event = asyncio.Event()

        # -------------------------------
        # Timing & analytics
        # -------------------------------
        self.session_start_time: float = time.time()
        self.last_activity_time: float = time.time()

        # Example metrics:
        # {
        #   "stt_latency": 0.0,
        #   "llm_latency": 0.0,
        #   "tts_latency": 0.0,
        #   "total_turn_latency": 0.0
        # }
        self.latency_metrics: dict = {}

    # ============================================================
    # State Management
    # ============================================================

    def set_state(self, new_state: str):
        """
        Update session state.
        Allowed states:
        - idle
        - listening
        - processing
        - speaking
        """
        valid_states = {"idle", "listening", "processing", "speaking"}
        if new_state not in valid_states:
            raise SessionStateError(f"Invalid session state: {new_state}. Valid states: {valid_states}")
        
        self.state = new_state
        self.last_activity_time = time.time()

    def increment_response_id(self):
        """
        Used for barge-in handling.
        Increments response ID to invalidate previous streams.
        """
        self.current_response_id += 1
        
    def get_session_duration(self) -> float:
        return time.time() - self.session_start_time

    # ============================================================
    # Barge-in Handling
    # ============================================================

    def trigger_barge_in(self):
        """
        Stops current speaking stream safely.
        """
        self.is_speaking = False
        self.increment_response_id()
        self.cancel_event.set()

    # ============================================================
    # Metrics
    # ============================================================

    def record_latency(self, key: str, value: float):
        """
        Store latency metric.
        """
        self.latency_metrics[key] = value

    # ============================================================
    # Reset
    # ============================================================

    def reset_session(self):
        """
        Reset transient session state.
        Keeps provider references intact.
        """

        self.state = "idle"
        self.is_speaking = False
        self.current_response_id = 0

        self.ignore_barge_in_once = False
        self.last_user_text = None
        self.last_final_transcript_time = 0.0

        self.cancel_event.clear()

        self.last_activity_time = time.time()
        self.latency_metrics.clear()
