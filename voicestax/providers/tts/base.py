from abc import ABC, abstractmethod


class BaseTTSProvider(ABC):

    @abstractmethod
    def validate_api_key(self) -> bool:
        pass

    @abstractmethod
    def stream_tts(self, text: str):
        pass
