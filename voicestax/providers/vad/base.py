"""Abstract base class for voice activity detection implementations.

This module defines the common interface used by VAD backends, requiring
concrete implementations to classify incoming audio chunks as speech or
non-speech through the is_speech method.
"""

from abc import ABC, abstractmethod

class BaseVAD(ABC):
    @abstractmethod
    def is_speech(self, audio_chunk: bytes) -> bool:
        pass