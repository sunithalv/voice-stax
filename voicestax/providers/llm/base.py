# Base interface for LLM providers.
# This module defines the common contract that concrete language model providers
# must implement for API key validation and chat streaming.

from abc import ABC, abstractmethod
from typing import Any,Iterator

class BaseLLMProvider(ABC):

    @abstractmethod
    def validate_api_key(self) -> bool:
        pass

    @abstractmethod
    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[Any]:
        pass
