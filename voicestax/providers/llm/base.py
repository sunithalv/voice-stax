from abc import ABC, abstractmethod


class BaseLLMProvider(ABC):

    @abstractmethod
    def validate_api_key(self) -> bool:
        pass

    @abstractmethod
    def stream_chat(self, messages):
        pass
