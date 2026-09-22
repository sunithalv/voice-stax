"""
ChatEngine manages conversation history, builds LLM message payloads,
streams responses, and stops early when a session interrupt is requested.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from voicestax.schemas.llm_schemas import LLMResponse
from voicestax.utils.exceptions import LLMError
from voicestax.utils.logger import logger


class ChatEngine:
    """Manage conversation history and interact with an LLM provider."""

    def __init__(
        self,
        llm_client,
        max_history: int = 12,
    ):
        # If max_history is too small, the conversation may be cut off too early
        # So 6 user assistant message pairs are kept
        if max_history < 2:
            raise ValueError(
                "max_history must be at least 2"
            )

        self.llm_client = llm_client
        self.max_history = max_history

    def _trim_history(
        self,
        history: list[dict[str, Any]],
    ) -> None:
        """
        Keep the most recent complete conversation turns.

        A turn normally consists of one user message and one assistant
        message. The system message is not stored in conversation history.
        """

        if len(history) <= self.max_history:
            return

        trimmed = history[-self.max_history :]

        # Avoid starting with an orphan assistant message.
        if trimmed and trimmed[0].get("role") == "assistant":
            trimmed = trimmed[1:]

        history[:] = trimmed

    def _build_messages(
        self,
        session,
    ) -> list[dict[str, str]]:
        """Build the system message plus conversation history."""

        system_prompt = session.settings.llm_system_prompt

        return [
            {
                "role": "system",
                "content": system_prompt,
            },
            *session.conversation_history,
        ]

    async def _stream_response(
        self,
        messages: list[dict[str, str]],
        session,
    ) -> str:
        """
        Execute the synchronous provider stream in a worker thread.

        This prevents the synchronous SDK from blocking the
        asyncio event loop.
        """

        def consume_stream() -> str:
            full_response = ""
            
            # Call the provider's stream_chat method to get a streaming response.
            stream = self.llm_client.stream_chat(
                messages=messages
            )
            
            # Iterate over the streaming chunks and build the full response.
            for chunk in stream:
                # Check if the session has been interrupted (e.g., by barge-in).
                if session.cancel_event.is_set():
                    logger.info(
                        "%s [LLM] Streaming interrupted by barge-in",
                        session.log_prefix(),
                    )
                    break

                try:
                    choices = chunk.choices
                    
                    if not choices:
                        continue

                    delta = choices[0].delta

                    if delta and delta.content:
                        full_response += delta.content

                except (AttributeError, IndexError, TypeError) as exc:
                    logger.warning(
                        "%s [LLM] Ignoring malformed stream chunk: %s",
                        session.log_prefix(),
                        exc,
                    )

            return full_response

        return await asyncio.to_thread(consume_stream)

    async def get_intent_and_response(
        self,
        user_text: str,
        session,
    ) -> LLMResponse:
        """
        Generate an intent and response using one LLM call.

        The provider must implement:

            stream_chat(messages=messages)

        The provider should return an iterable of streaming chunks.
        """

        if not user_text or not user_text.strip():
            raise LLMError(
                "User text cannot be empty"
            )

        history = session.conversation_history

        user_message = {
            "role": "user",
            "content": user_text.strip(),
        }
        
        # Add user message to session history before sending to LLM
        history.append(user_message)
        self._trim_history(history)

       # Build the full message payload including system prompt and conversation history
        messages = self._build_messages(session)

        full_response = ""
        interrupted = False

        # Record the time when the LLM request starts for latency metrics
        session.llm_start_time = time.perf_counter()

        logger.info(
            "%s [LLM] Sending request: messages=%d",
            session.log_prefix(),
            len(messages),
        )

        try:
            # Stream the response from the LLM provider in a separate thread to avoid blocking the event loop.
            full_response = await self._stream_response(
                messages=messages,
                session=session,
            )
            
            # Check if the session was interrupted during streaming (e.g., by barge-in).
            interrupted = session.cancel_event.is_set()

        except Exception as exc:
            # Remove the user message if the LLM request failed.
            if history and history[-1] is user_message:
                history.pop()

            logger.error(
                "%s [LLM ERROR] Request failed: %s: %s",
                session.log_prefix(),
                type(exc).__name__,
                exc,
            )

            raise LLMError(
                f"LLM request failed: {exc}"
            ) from exc

        finally:
            # Record the time when the LLM request ends for latency metrics
            session.llm_end_time = time.perf_counter()

            # Calculate the latency in milliseconds and record it in the session's latency metrics.
            llm_latency = (
                session.llm_end_time
                - session.llm_start_time
            ) * 1000

            session.record_latency(
                "llm_latency",
                round(llm_latency, 2),
            )

            logger.info(
                "%s [LLM] Stream finished: chars=%d latency=%.2f ms",
                session.log_prefix(),
                len(full_response),
                llm_latency,
            )
        
        # Handle interrupted or empty responses, and parse the structured response if available.
        if interrupted:
            logger.info(
                "%s [LLM] Discarding interrupted partial response",
                session.log_prefix(),
            )

            # Remove the user message because no valid assistant turn
            # was completed.
            if history and history[-1] is user_message:
                history.pop()

            raise LLMError(
                "LLM response interrupted by barge-in"
            )
        
        # Handle empty responses by removing the user message and raising an error.
        if not full_response.strip():
            if history and history[-1] is user_message:
                history.pop()

            logger.error(
                "%s [LLM ERROR] Empty response received",
                session.log_prefix(),
            )

            raise LLMError(
                "LLM returned an empty response"
            )

        try:
            # Parse the full response as JSON to extract the intent and response fields.
            parsed = LLMResponse.model_validate_json(
                full_response
            )

            logger.info(
                "%s [LLM] Structured response parsed successfully: "
                "intent=%s",
                session.log_prefix(),
                parsed.intent,
            )

        except Exception as exc:
            logger.warning(
                "%s [LLM] Structured response parsing failed; "
                "using raw response fallback: %s",
                session.log_prefix(),
                exc,
            )
            
            # Use the raw response as a fallback if structured parsing fails.
            parsed = LLMResponse(
                intent="conversation",
                response=full_response,
            )
        # Append the assistant's response to the session conversation history 
        history.append(
            {
                "role": "assistant",
                "content": parsed.response,
            }
        )

        self._trim_history(history)

        logger.info(
            "%s [LLM] Response ready: intent=%s chars=%d",
            session.log_prefix(),
            parsed.intent,
            len(parsed.response),
        )

        return parsed