from groq import Groq
from voicestax.providers.llm.base import BaseLLMProvider
from voicestax.utils.exceptions import LLMConnectionError, LLMValidationError, LLMStreamingError
import requests


class GroqLLMProvider(BaseLLMProvider):

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile", 
                 max_tokens: int = 120):
            self.client = Groq(api_key=api_key)
            self.model = model 
            self.max_tokens = max_tokens 

    def validate_api_key(self) -> bool:
        try:
            self.client.models.list()
            return True
        except requests.exceptions.ConnectionError as e:
            raise LLMConnectionError(f"Failed to connect to Groq API: {e}") from e
        except Exception as e:
            # Could be authentication error or other API error
            raise LLMValidationError(f"Groq API validation failed: {e}") from e

    def stream_chat(self, messages):
        try:
            return self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                max_tokens=self.max_tokens,
            )
        except requests.exceptions.ConnectionError as e:
            raise LLMConnectionError(f"Failed to connect to Groq API during chat: {e}") from e
        except Exception as e:
            raise LLMStreamingError(f"Groq chat streaming failed: {e}") from e
