# VoiceStax/core/timing.py

"""
Word timing, delays, and synchronization logic for TTS streaming in the frontend.
"""

from typing import Optional


def calculate_word_delays(
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


def get_audio_finish_delay(default_delay: float = 0.3) -> float:
    """Delay after audio finishes before next action."""
    return default_delay
