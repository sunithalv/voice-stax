# Base interface for speech-to-text providers, defining the streaming
# lifecycle and audio delivery methods that concrete providers must implement.

from abc import ABC, abstractmethod
from typing import Callable


class BaseSTTProvider(ABC):
    
    @property
    @abstractmethod
    def is_ready(self) -> bool:
        pass

    @abstractmethod
    def validate_api_key(self) -> bool:
        pass

    @abstractmethod
    def start_streaming(
        self,
        on_transcript: Callable[[str, bool], None],
        on_error: Callable[[Exception], None],
    )-> None:
        pass

    @abstractmethod
    def stop_streaming(self)-> None:
        pass

    @abstractmethod
    def is_listening(self) -> bool:
        pass

    @abstractmethod
    async def send_audio(self, audio_chunk: bytes):
        """Send audio chunk to STT service"""
        pass
