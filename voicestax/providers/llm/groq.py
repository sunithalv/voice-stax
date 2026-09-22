"""
Groq-backed LLM provider implementation.

This provider:
- Creates a Groq client.
- Streams chat completions.
- Keeps provider defaults inside the provider.
- Accepts arbitrary Groq-specific parameters through **kwargs.
- Logs provider lifecycle and streaming errors.
- Never logs the API key.
"""

from typing import Any

from groq import Groq

from voicestax.providers.llm.base import BaseLLMProvider
from voicestax.utils import session
from voicestax.utils.exceptions import (
    LLMStreamingError,
    LLMValidationError,
)
from voicestax.utils.logger import logger


class GroqLLMProvider(BaseLLMProvider):
    """
    Groq LLM provider.

    Known parameters used directly by VoiceStax:

    - model
    - max_tokens

    Additional parameters are accepted through **kwargs and passed to:

        client.chat.completions.create(...)

    This allows users to supply new Groq parameters without requiring
    a VoiceStax source-code update.

    Example:

        GroqLLMProvider(
            api_key="...",
            model="llama-3.3-70b-versatile",
            max_tokens=120,
            temperature=0.2,
            top_p=0.9,
        )
    """

    DEFAULTS: dict[str, Any] = {
        "model": "llama-3.3-70b-versatile",
        "max_tokens": 120,
    }

    def __init__(
        self,
        api_key: str,
        **kwargs: Any,
    ):
        """
        Initialize the Groq provider.

        The API key is required. Provider-specific parameters are merged
        with the defaults and stored for use during streaming.
        """

        if not api_key:
            raise LLMValidationError(
                "Groq API key is required"
            )


        # Merge provider defaults with user-supplied configuration.
        # User values override the defaults.
        self.config: dict[str, Any] = {
            **self.DEFAULTS,
            **kwargs,
        }

        self.validate_config(self.config)

        # Values directly used by VoiceStax.
        self.model = self.config["model"]
        self.max_tokens = self.config["max_tokens"]

        # Keep all additional provider-specific values. These will be
        # passed to Groq's chat completion endpoint.
        self.extra_config = {
            key: value
            for key, value in self.config.items()
            if key not in self.DEFAULTS
        }

        # The client is created once and reused for the provider lifetime.
        self.client = Groq(api_key=api_key)

        logger.debug(
            "%s [Groq] Provider initialized. "
            "model=%s, max_tokens=%s, extra_config_keys=%s",
            session.get_log_prefix(),
            self.model,
            self.max_tokens,
            sorted(self.extra_config.keys()),
        )

    def validate_config(self, config: dict[str, Any]) -> None:
        """
        Validate values that VoiceStax uses directly.

        Groq-specific parameters are not checked against a hardcoded
        allow-list. Groq remains responsible for validating supported
        parameter names and values when the request is made.
        """

        model = config.get("model")

        if not isinstance(model, str) or not model.strip():
            raise ValueError(
                "Groq model must be a non-empty string"
            )

        max_tokens = config.get("max_tokens")

        if (
            not isinstance(max_tokens, int)
            or isinstance(max_tokens, bool)
            or max_tokens <= 0
        ):
            raise ValueError(
                "Groq max_tokens must be a positive integer"
            )



    def validate_api_key(self) -> bool:
        """
        Validate the Groq API key.

        This performs a live API validation by requesting the available
        model list. Authentication or network failures are converted
        into LLMValidationError.
        """

        logger.debug(
            "%s [Groq] Validating API key",
            session.get_log_prefix(),
        )

        try:
            self.client.models.list()

            logger.info(
                "%s [Groq] API key validation succeeded",
                session.get_log_prefix(),
            )

            return True

        except Exception as exc:
            logger.error(
                "%s [Groq] API key validation failed: %s: %s",
                session.get_log_prefix(),
                type(exc).__name__,
                exc,
            )

            raise LLMValidationError(
                f"Groq API validation failed: {exc}"
            ) from exc

    def stream_chat(self, messages):
        """
        Stream a chat completion from Groq.

        The returned object is the Groq streaming response iterator.
        The caller can iterate over it and process each streamed chunk.
        """

        if not messages:
            raise LLMStreamingError(
                "Groq messages cannot be empty"
            )

        params: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "max_tokens": self.max_tokens,
        }

        # Forward additional provider-specific parameters such as:
        # temperature, top_p, stop, seed, response_format, tools, etc.
        #
        # Groq will validate whether a particular parameter is supported
        # by the selected model and endpoint.
        params.update(self.extra_config)

        # Do not log the complete messages because they may contain
        # private conversation content or customer information.
        logger.debug(
            "%s [Groq] Starting chat stream. "
            "model=%s, message_count=%s, parameter_keys=%s",
            session.get_log_prefix(),
            self.model,
            len(messages),
            sorted(params.keys()),
        )

        try:
            response = self.client.chat.completions.create(
                **params
            )

            logger.debug(
                "%s [Groq] Chat stream created successfully",
                session.get_log_prefix(),
            )

            return response

        except Exception as exc:
            logger.error(
                "%s [Groq] Chat streaming failed: %s: %s",
                session.get_log_prefix(),
                type(exc).__name__,
                exc,
            )

            raise LLMStreamingError(
                f"Groq chat streaming failed: {exc}"
            ) from exc