from abc import ABC, abstractmethod
from typing import Callable


class BaseSTTProvider(ABC):
    
    @property
    def is_ready(self) -> bool:
        return False

    @abstractmethod
    def validate_api_key(self) -> bool:
        pass

    @abstractmethod
    def start_streaming(
        self,
        on_transcript: Callable[[str, bool], None],
        on_error: Callable[[Exception], None],
    ):
        pass

    @abstractmethod
    def stop_streaming(self):
        pass

    @abstractmethod
    def is_listening(self) -> bool:
        pass

    @abstractmethod
    async def send_audio(self, audio_chunk: bytes):
        """Send audio chunk to STT service"""
        pass
